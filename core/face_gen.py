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
    "half_open": (0.18, 0.05, 0.0, 0.06),
    "open": (0.42, 0.08, 0.0, 0.16),
    "rounded": (0.22, 0.06, 0.15, 0.08),
}

def _lip_indices() -> list[int]:
    idx = set()
    for a, b in mp.solutions.face_mesh.FACEMESH_LIPS:
        idx.add(a)
        idx.add(b)
    return sorted(idx)


def _oval_indices() -> list[int]:
    idx = set()
    for a, b in mp.solutions.face_mesh.FACEMESH_FACE_OVAL:
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

    # Arco de mandibula/menton: solo los puntos del ovalo de la cara que
    # caen debajo de la boca y dentro de su ancho (con margen) - así no se
    # arrastran puntos de las mejillas/orejas, que estarian mas arriba o
    # muy a los lados.
    mouth_bottom_y = float(lip_points[:, 1].max())
    mouth_w = float(corners[1, 0] - corners[0, 0])
    margin = mouth_w * 0.35
    jaw_points = np.array(
        [
            pt(i)
            for i in _oval_indices()
            if pt(i)[1] > mouth_bottom_y
            and corners[0, 0] - margin <= pt(i)[0] <= corners[1, 0] + margin
        ],
        dtype=np.float32,
    )

    left_idx, right_idx = _eye_indices()
    left_eye = np.array([pt(i) for i in left_idx], dtype=np.float32)
    right_eye = np.array([pt(i) for i in right_idx], dtype=np.float32)

    return lip_points, corners, jaw_points, left_eye, right_eye


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
    """Pinta un hueco oscuro (interior de boca) entre labios separados.

    El warp por si solo solo estira piel/labio existente - no puede
    revelar dientes ni cavidad oral que no estan en la foto. Sin esto,
    'abrir la boca' se ve como un manchon de piel estirada en vez de una
    boca abierta."""
    if upper_amt <= 0 and lower_amt <= 0:
        return img

    n = 13
    t = np.linspace(0.0, 1.0, n)
    xs = left_x + (right_x - left_x) * t
    shape = np.sin(np.pi * t) ** 0.7
    upper_ys = center_y - upper_amt * shape
    lower_ys = center_y + lower_amt * shape
    upper_pts = np.stack([xs, upper_ys], axis=1)
    lower_pts = np.stack([xs[::-1], lower_ys[::-1]], axis=1)
    poly = np.vstack([upper_pts, lower_pts]).astype(np.int32)

    fill = np.full_like(img, (35, 25, 55))  # BGR: interior oscuro rojizo
    mask = np.zeros(img.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    mask = cv2.GaussianBlur(mask, (5, 5), 0)
    mask3 = (cv2.merge([mask, mask, mask]).astype(np.float32)) / 255.0

    blended = (fill.astype(np.float32) * 0.85 + img.astype(np.float32) * 0.15)
    return (blended * mask3 + img.astype(np.float32) * (1 - mask3)).astype(np.uint8)


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
    jaw_local: np.ndarray,
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

    jaw_src = jaw_local.copy()
    jaw_dst = jaw_local.copy()
    if dy_jaw_frac and len(jaw_local):
        # El menton (centro del arco) baja mas que los extremos cerca de
        # las comisuras, para que se vea como una rotacion de mandibula
        # en vez de un bloque completo deslizandose hacia abajo.
        half_w = float(np.max(np.abs(jaw_local[:, 0] - center_x))) or 1.0
        weight = 1.0 - 0.5 * np.clip(np.abs(jaw_src[:, 0] - center_x) / half_w, 0, 1)
        jaw_dst[:, 1] += dy_jaw_frac * mouth_h * weight

    src = np.vstack([src, jaw_src]) if len(jaw_src) else src
    dst = np.vstack([dst, jaw_dst]) if len(jaw_dst) else dst

    warped = _tps_warp(crop, src, dst)

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

    lip_points, corners, jaw_points, left_eye, right_eye = _detect_face_points(image)

    # --- Boca + mandibula ---
    lip_w = float(lip_points[:, 0].max() - lip_points[:, 0].min())
    lip_h = float(lip_points[:, 1].max() - lip_points[:, 1].min())
    mouth_points = np.vstack([lip_points, jaw_points]) if len(jaw_points) else lip_points
    bx, by, bw, bh = _bbox_from_points(
        mouth_points, (h, w), pad_x=lip_w * 0.6, pad_top=lip_h * 0.9, pad_bottom=lip_h * 0.5
    )
    mouth_crop = image[by : by + bh, bx : bx + bw]

    points_local = lip_points - np.array([bx, by], dtype=np.float32)
    corners_local = corners - np.array([bx, by], dtype=np.float32)
    jaw_local = (
        jaw_points - np.array([bx, by], dtype=np.float32)
        if len(jaw_points)
        else jaw_points
    )
    center_y = float(np.mean(corners_local[:, 1]))
    x0, y0 = points_local.min(axis=0)
    x1, y1 = points_local.max(axis=0)
    mouth_w, mouth_h = float(x1 - x0), float(y1 - y0)

    MOUTH_OUT_DIR.mkdir(parents=True, exist_ok=True)
    mouth_shapes: dict[str, str] = {}
    for name, (dy_lower, dy_upper, dx_corner, dy_jaw) in MOUTH_SHAPES.items():
        warped = _warp_mouth(
            mouth_crop, points_local, corners_local, jaw_local, center_y, mouth_w, mouth_h,
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
