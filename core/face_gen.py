"""Generador offline de formas de boca/mandibula y parpadeo para el rostro
animado.

No corre en runtime de la app: se ejecuta a mano (`python -m core.face_gen`)
cada vez que se cambia la imagen base en config/settings.json ("face" ->
"base_image"). Detecta la cara con mediapipe y genera, deformando el pixel
existente con thin-plate-spline (TPS):

- Variantes de boca (cerrada/semi-abierta/abierta/redondeada), incluyendo un
  poco de caida de mandibula/menton para que no se vea como una boca
  flotando sobre una quijada inmovil.
- Un estado de ojos cerrados (para parpadeo), sobre ambos ojos a la vez.

Escribe ui/assets/face/manifest.js con las rutas y los bbox para que el
frontend sepa donde superponer cada pieza.

Es una tecnica de "puppeting" 2D barata (deforma pixeles existentes), no un
modelo generativo: no inventa dientes, interior de boca ni globo ocular que
no esten en la foto. Sirve como punto de reemplazo si mas adelante se
quiere enchufar algo mas realista (otra foto, piezas dibujadas a mano, o un
pipeline neuronal).
"""

import json

import cv2
import mediapipe as mp
import numpy as np

from core.config import ROOT, load_settings

MOUTH_OUT_DIR = ROOT / "ui" / "assets" / "face" / "mouth"
EYES_OUT_DIR = ROOT / "ui" / "assets" / "face" / "eyes"
MANIFEST_PATH = ROOT / "ui" / "assets" / "face" / "manifest.js"

LEFT_CORNER = 61
RIGHT_CORNER = 291

# (dy_lower, dy_upper, dx_corner, dy_jaw) como fraccion de la altura/ancho
# de la boca. dy_lower > 0 empuja el labio inferior hacia abajo; dy_upper <
# 0 levanta un poco el labio superior; dx_corner > 0 acerca las comisuras
# al centro (boca redondeada); dy_jaw > 0 baja el menton/mandibula, mas
# suave que el labio para que se vea como rotacion de quijada y no un
# bloque deslizandose.
MOUTH_SHAPES = {
    "closed": (0.0, 0.0, 0.0, 0.0),
    "half_open": (0.18, 0.05, 0.0, 0.10),
    "open": (0.42, 0.08, 0.0, 0.24),
    "rounded": (0.22, 0.06, 0.15, 0.14),
}

# Esta imagen base es una placa mecanica con forma de mandibula, no piel
# real. La piel de la barbilla termina y empieza la placa rigida a
# ~0.86x el alto de labio por debajo del labio inferior (medido a mano
# en esta foto); la placa sigue siendo visible/util para el recorte
# hasta ~1.9x mas abajo, antes de que empiecen los cables oscuros del
# cuello. Si se cambia la foto base, hay que volver a medir esto.
PLATE_SEAM_FRAC = 0.86
PLATE_REACH_FRAC = 1.9


def _lip_indices() -> list[int]:
    idx = set()
    for a, b in mp.solutions.face_mesh.FACEMESH_LIPS:
        idx.add(a)
        idx.add(b)
    return sorted(idx)


def _eye_indices() -> tuple[list[int], list[int]]:
    left = set()
    for a, b in mp.solutions.face_mesh.FACEMESH_LEFT_EYE:
        left.add(a)
        left.add(b)
    right = set()
    for a, b in mp.solutions.face_mesh.FACEMESH_RIGHT_EYE:
        right.add(a)
        right.add(b)
    return sorted(left), sorted(right)


def _detect_face_points(image_bgr: np.ndarray):
    """Corre mediapipe una sola vez y devuelve todos los grupos de puntos
    que necesitamos: labios, comisuras, arco de mandibula bajo la boca, y
    contorno de cada ojo."""
    h, w = image_bgr.shape[:2]
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=True
    ) as face_mesh:
        result = face_mesh.process(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    if not result.multi_face_landmarks:
        raise RuntimeError("No se detecto ninguna cara en la imagen base.")
    landmarks = result.multi_face_landmarks[0].landmark

    def pt(i: int) -> tuple[float, float]:
        return (landmarks[i].x * w, landmarks[i].y * h)

    lip_points = np.array([pt(i) for i in _lip_indices()], dtype=np.float32)
    corners = np.array([pt(LEFT_CORNER), pt(RIGHT_CORNER)], dtype=np.float32)

    left_idx, right_idx = _eye_indices()
    left_eye = np.array([pt(i) for i in left_idx], dtype=np.float32)
    right_eye = np.array([pt(i) for i in right_idx], dtype=np.float32)

    return lip_points, corners, left_eye, right_eye


def _bbox_from_points(
    points: np.ndarray,
    image_shape: tuple[int, int],
    pad_x: float,
    pad_top: float,
    pad_bottom: float,
) -> tuple[int, int, int, int]:
    h, w = image_shape
    x0, y0 = points.min(axis=0)
    x1, y1 = points.max(axis=0)
    x0 = max(0, int(x0 - pad_x))
    y0 = max(0, int(y0 - pad_top))
    x1 = min(w, int(x1 + pad_x))
    y1 = min(h, int(y1 + pad_bottom))
    return x0, y0, x1 - x0, y1 - y0


def _paint_gap(
    img: np.ndarray,
    left_x: float,
    right_x: float,
    center_y: float,
    upper_amt: float,
    lower_amt: float,
) -> np.ndarray:
    """Pinta el interior de boca entre labios separados: una franja clara
    de "dientes" justo bajo el labio superior, y cavidad oscura debajo.

    El warp por si solo solo estira piel/labio existente - no puede
    revelar dientes ni cavidad oral que no estan en la foto. Sin esto,
    'abrir la boca' se ve como un hueco liso de un solo color en vez de
    una boca real."""
    if upper_amt <= 0 and lower_amt <= 0:
        return img

    n = 13
    t = np.linspace(0.0, 1.0, n)
    xs = left_x + (right_x - left_x) * t
    shape = np.sin(np.pi * t) ** 0.7
    upper_ys = center_y - upper_amt * shape
    lower_ys = center_y + lower_amt * shape
    teeth_ys = upper_ys + 0.32 * (lower_ys - upper_ys)

    def _poly(top_ys: np.ndarray, bottom_ys: np.ndarray) -> np.ndarray:
        top_pts = np.stack([xs, top_ys], axis=1)
        bottom_pts = np.stack([xs[::-1], bottom_ys[::-1]], axis=1)
        return np.vstack([top_pts, bottom_pts]).astype(np.int32)

    def _blend(base: np.ndarray, poly: np.ndarray, color: tuple, blur: int) -> np.ndarray:
        mask = np.zeros(base.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [poly], 255)
        if blur:
            mask = cv2.GaussianBlur(mask, (blur, blur), 0)
        mask3 = (cv2.merge([mask, mask, mask]).astype(np.float32)) / 255.0
        fill = np.full_like(base, color)
        return (fill.astype(np.float32) * mask3 + base.astype(np.float32) * (1 - mask3))

    out = _blend(img, _poly(upper_ys, lower_ys), (22, 20, 24), 5)  # BGR: cavidad oscura neutra
    out = out.astype(np.uint8)

    # Dientes individuales, no una franja solida: se dibujan como bloques
    # separados por huecos reales (color de cavidad), sin blur. Una raya
    # divisoria fina de un solo pixel desaparece al reescalar la imagen
    # al tamano final del sprite en la UI (~0.2x) - un hueco con ancho de
    # verdad sobrevive esa reduccion.
    n_teeth = 6
    gap_frac = 0.16
    for i in range(n_teeth):
        f0 = i / n_teeth + gap_frac / (2 * n_teeth)
        f1 = (i + 1) / n_teeth - gap_frac / (2 * n_teeth)
        top0, top1 = np.interp([f0, f1], t, upper_ys)
        bot0, bot1 = np.interp([f0, f1], t, teeth_ys)
        if min(bot0 - top0, bot1 - top1) < 2:
            continue
        x0 = left_x + (right_x - left_x) * f0
        x1 = left_x + (right_x - left_x) * f1
        tooth_poly = np.array(
            [[x0, top0], [x1, top1], [x1, bot1], [x0, bot0]], dtype=np.int32
        )
        cv2.fillConvexPoly(out, tooth_poly, (200, 206, 214))  # BGR: dientes

    return out


def _paint_lid_line(img: np.ndarray, left_x: float, right_x: float, y: float) -> np.ndarray:
    """Pliegue fino y curvo donde quedan las pestanas al cerrar el ojo -
    sin esto, el relleno de piel se ve como un parche liso en vez de un
    parpado cerrado."""
    overlay = img.copy()
    n = 20
    t = np.linspace(0.0, 1.0, n)
    xs = left_x + (right_x - left_x) * t
    # ligera curva hacia abajo en el centro, como un pliegue de parpado
    ys = y + 1.5 * np.sin(np.pi * t)
    pts = np.stack([xs, ys], axis=1).astype(np.int32)
    cv2.polylines(overlay, [pts], False, (45, 35, 35), 1, cv2.LINE_AA)
    return cv2.addWeighted(overlay, 0.5, img, 0.5, 0)


def _shift_plate_down(crop: np.ndarray, warped: np.ndarray, plate_y: int, shift_px: int) -> np.ndarray:
    """Baja la placa/menton con un remap suave, sin deformar su
    geometria rigida (bordes rectos, tornillos) y sin cortar de borde a
    borde del recorte.

    Primera version: desplazaba TODO el ancho del recorte por igual (un
    corte recto). Pero las placas metalicas de los lados de la cara
    siguen MAS ALLA del recorte, sin moverse - la costura entre "adentro
    del recorte, desplazado" y "afuera, quieto" se notaba como una linea
    que descontinuaba esas lineas del diseño justo en el borde del
    recorte. Ahora el desplazamiento se atenua horizontalmente hasta
    CERO exactamente en los bordes del recorte (para calzar con el
    mundo de afuera, que no se mueve) y es maximo en el centro, donde
    esta el menton; verticalmente se activa de forma gradual alrededor
    de PLATE_SEAM_FRAC en vez de un corte duro."""
    h, w = crop.shape[:2]
    plate_y = max(1, min(plate_y, h - 1))
    if shift_px <= 0:
        return warped

    ramp = 14
    y_top = max(0, plate_y - ramp)
    y_bottom = min(h, plate_y + ramp)

    x_weight = np.sin(np.linspace(0.0, np.pi, w, dtype=np.float32))  # 0 en los bordes, 1 en el centro
    y_ramp = np.clip((np.arange(h, dtype=np.float32) - y_top) / max(y_bottom - y_top, 1), 0.0, 1.0)
    y_ramp = y_ramp * y_ramp * (3 - 2 * y_ramp)  # smoothstep, sin quiebre en los extremos

    dy = shift_px * y_ramp[:, None] * x_weight[None, :]
    map_x, map_y = np.meshgrid(
        np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32)
    )
    shifted = cv2.remap(
        crop, map_x, map_y - dy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )

    alpha = y_ramp[:, None, None]
    blended = warped.astype(np.float32) * (1 - alpha) + shifted.astype(np.float32) * alpha
    return blended.astype(np.uint8)


def _tps_warp(crop: np.ndarray, src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    ch, cw = crop.shape[:2]
    anchors = np.array(
        [
            [0, 0], [cw / 2, 0], [cw - 1, 0],
            [0, ch / 2], [cw - 1, ch / 2],
            [0, ch - 1], [cw / 2, ch - 1], [cw - 1, ch - 1],
        ],
        dtype=np.float32,
    )
    src_all = np.vstack([src, anchors]).reshape(1, -1, 2)
    dst_all = np.vstack([dst, anchors]).reshape(1, -1, 2)
    matches = [cv2.DMatch(i, i, 0) for i in range(src_all.shape[1])]
    tps = cv2.createThinPlateSplineShapeTransformer()
    tps.estimateTransformation(dst_all, src_all, matches)
    return tps.warpImage(crop)


def _warp_mouth(
    crop: np.ndarray,
    points_local: np.ndarray,
    corners_local: np.ndarray,
    plate_y_local: int,
    center_y: float,
    mouth_w: float,
    mouth_h: float,
    dy_lower_frac: float,
    dy_upper_frac: float,
    dx_corner_frac: float,
    dy_jaw_frac: float,
) -> np.ndarray:
    if (
        dy_lower_frac == 0 and dy_upper_frac == 0
        and dx_corner_frac == 0 and dy_jaw_frac == 0
    ):
        return crop.copy()

    src = points_local.copy()
    dst = points_local.copy()

    is_corner = np.zeros(len(points_local), dtype=bool)
    for corner in corners_local:
        dists = np.linalg.norm(points_local - corner, axis=1)
        is_corner |= dists < 1e-3

    below = points_local[:, 1] > center_y
    dst[below, 1] += dy_lower_frac * mouth_h
    dst[~below, 1] -= dy_upper_frac * mouth_h

    center_x = float(np.mean(corners_local[:, 0]))
    if dx_corner_frac:
        for i in np.where(is_corner)[0]:
            dx = (center_x - src[i, 0]) * dx_corner_frac
            dst[i, 0] += dx

    warped = _tps_warp(crop, src, dst)

    if dy_jaw_frac:
        warped = _shift_plate_down(
            crop, warped, plate_y_local, int(round(dy_jaw_frac * mouth_h))
        )

    left_x, right_x = float(corners_local[0, 0]), float(corners_local[1, 0])
    warped = _paint_gap(
        warped, left_x, right_x, center_y,
        upper_amt=dy_upper_frac * mouth_h,
        lower_amt=dy_lower_frac * mouth_h,
    )
    return warped


def _close_eye_paint(crop: np.ndarray, eye_local: np.ndarray) -> np.ndarray:
    """Cierra un ojo pintando la apertura con un tono de piel tomado del
    propio recorte, en vez de deformarla con TPS.

    Comprimir geometricamente un ojo abierto hasta casi cerrarlo pliega
    la malla del warp (incluso ya con cada ojo en su propio recorte
    ajustado) y deja huecos negros donde ningun pixel de origen cae. A
    este tamano de sprite, pintar encima con el tono de piel del propio
    recorte (banda inferior, mejilla limpia) mas una linea de pestana se
    ve mejor y es mucho mas robusto."""
    ch, cw = crop.shape[:2]
    band = crop[int(ch * 0.85) :, :]
    fill_color = band.reshape(-1, 3).mean(axis=0)

    hull = cv2.convexHull(eye_local.astype(np.int32))
    mask = np.zeros((ch, cw), dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull, 255)
    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8))
    mask = cv2.GaussianBlur(mask, (13, 13), 0)
    mask3 = (cv2.merge([mask, mask, mask]).astype(np.float32)) / 255.0

    fill = np.full_like(crop, fill_color)
    out = (fill.astype(np.float32) * mask3 + crop.astype(np.float32) * (1 - mask3)).astype(np.uint8)

    left_x, right_x = float(eye_local[:, 0].min()), float(eye_local[:, 0].max())
    center_y = float(np.mean(eye_local[:, 1]))
    return _paint_lid_line(out, left_x, right_x, center_y)


def generate() -> None:
    settings = load_settings()
    base_rel = settings["face"]["base_image"]
    base_path = ROOT / base_rel

    image = cv2.imread(str(base_path))
    if image is None:
        raise RuntimeError(f"No pude leer la imagen base: {base_path}")
    h, w = image.shape[:2]

    lip_points, corners, left_eye, right_eye = _detect_face_points(image)

    # --- Boca + mandibula ---
    lip_w = float(lip_points[:, 0].max() - lip_points[:, 0].min())
    lip_h = float(lip_points[:, 1].max() - lip_points[:, 1].min())
    mouth_bottom_y = float(lip_points[:, 1].max())
    # el recorte llega hasta bien dentro de la placa (PLATE_REACH_FRAC),
    # pero solo la piel de labio/menton (hasta PLATE_SEAM_FRAC) se
    # deforma con TPS - la placa se desliza en bloque, ver
    # _shift_plate_down.
    bx, by, bw, bh = _bbox_from_points(
        lip_points, (h, w), pad_x=lip_w * 0.6, pad_top=lip_h * 0.9,
        pad_bottom=PLATE_REACH_FRAC * lip_h,
    )
    mouth_crop = image[by : by + bh, bx : bx + bw]

    points_local = lip_points - np.array([bx, by], dtype=np.float32)
    corners_local = corners - np.array([bx, by], dtype=np.float32)
    center_y = float(np.mean(corners_local[:, 1]))
    x0, y0 = points_local.min(axis=0)
    x1, y1 = points_local.max(axis=0)
    mouth_w, mouth_h = float(x1 - x0), float(y1 - y0)
    plate_y_local = int(round((mouth_bottom_y + PLATE_SEAM_FRAC * lip_h) - by))

    MOUTH_OUT_DIR.mkdir(parents=True, exist_ok=True)
    mouth_shapes: dict[str, str] = {}
    for name, (dy_lower, dy_upper, dx_corner, dy_jaw) in MOUTH_SHAPES.items():
        warped = _warp_mouth(
            mouth_crop, points_local, corners_local, plate_y_local, center_y, mouth_w, mouth_h,
            dy_lower, dy_upper, dx_corner, dy_jaw,
        )
        out_path = MOUTH_OUT_DIR / f"{name}.png"
        cv2.imwrite(str(out_path), warped)
        mouth_shapes[name] = f"assets/face/mouth/{name}.png"
        print(f"[face_gen] boca {name} -> {out_path}")

    # --- Ojos (parpadeo), cada uno en su propio recorte ajustado ---
    eyes_manifest: dict[str, dict] = {}
    for side, eye_pts in (("left", left_eye), ("right", right_eye)):
        eye_w = float(eye_pts[:, 0].max() - eye_pts[:, 0].min())
        eye_h = float(eye_pts[:, 1].max() - eye_pts[:, 1].min())
        exi, eyi, ewi, ehi = _bbox_from_points(
            eye_pts, (h, w), pad_x=eye_w * 0.25, pad_top=eye_h * 0.9, pad_bottom=eye_h * 0.9
        )
        eye_crop = image[eyi : eyi + ehi, exi : exi + ewi]
        eye_local = eye_pts - np.array([exi, eyi], dtype=np.float32)

        eye_out_dir = EYES_OUT_DIR / side
        eye_out_dir.mkdir(parents=True, exist_ok=True)
        shapes: dict[str, str] = {}
        for name, img_out in (
            ("open", eye_crop.copy()),
            ("closed", _close_eye_paint(eye_crop, eye_local)),
        ):
            out_path = eye_out_dir / f"{name}.png"
            cv2.imwrite(str(out_path), img_out)
            shapes[name] = f"assets/face/eyes/{side}/{name}.png"
            print(f"[face_gen] ojo {side} {name} -> {out_path}")

        eyes_manifest[side] = {
            "bbox": {"x": exi, "y": eyi, "w": ewi, "h": ehi},
            "shapes": shapes,
        }

    manifest = {
        "base_image": base_rel[3:] if base_rel.startswith("ui/") else base_rel,
        "base_size": {"w": w, "h": h},
        "mouth_bbox": {"x": bx, "y": by, "w": bw, "h": bh},
        "mouth_shapes": mouth_shapes,
        "eyes": eyes_manifest,
    }
    MANIFEST_PATH.write_text(
        "window.FACE_MANIFEST = " + json.dumps(manifest, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"[face_gen] manifest -> {MANIFEST_PATH}")


if __name__ == "__main__":
    generate()
