"""Generador offline de formas de boca para el rostro animado.

No corre en runtime de la app: se ejecuta a mano (`python -m core.face_gen`)
cada vez que se cambia la imagen base en config/settings.json ("face" ->
"base_image"). Detecta los labios con mediapipe, genera unas pocas
variantes de boca (cerrada/semi-abierta/abierta/redondeada) deformando el
recorte alrededor de la boca con un warp de thin-plate-spline, y escribe
ui/assets/face/manifest.js con las rutas y el bbox para que el frontend
sepa donde superponerlas.

Es una tecnica de "puppeting" 2D barata (deforma pixeles existentes), no
un modelo generativo: no inventa dientes ni interior de boca. Sirve como
punto de reemplazo si mas adelante se quiere enchufar algo mas realista
(otra foto, bocas dibujadas a mano, o un pipeline neuronal).
"""

import json

import cv2
import mediapipe as mp
import numpy as np

from core.config import ROOT, load_settings

OUT_DIR = ROOT / "ui" / "assets" / "face" / "mouth"
MANIFEST_PATH = ROOT / "ui" / "assets" / "face" / "manifest.js"

LEFT_CORNER = 61
RIGHT_CORNER = 291

# (dy_lower, dy_upper, dx_corner) como fraccion de la altura/ancho de la
# boca. dy_lower > 0 empuja el labio inferior hacia abajo; dy_upper < 0
# levanta un poco el labio superior; dx_corner > 0 acerca las comisuras
# al centro (boca redondeada).
MOUTH_SHAPES = {
    "closed": (0.0, 0.0, 0.0),
    "half_open": (0.18, 0.05, 0.0),
    "open": (0.42, 0.08, 0.0),
    "rounded": (0.22, 0.06, 0.15),
}


def _lip_indices() -> list[int]:
    idx = set()
    for a, b in mp.solutions.face_mesh.FACEMESH_LIPS:
        idx.add(a)
        idx.add(b)
    return sorted(idx)


def _detect_lip_points(image_bgr: np.ndarray) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=True
    ) as face_mesh:
        result = face_mesh.process(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    if not result.multi_face_landmarks:
        raise RuntimeError("No se detecto ninguna cara en la imagen base.")
    landmarks = result.multi_face_landmarks[0].landmark
    points = np.array(
        [(landmarks[i].x * w, landmarks[i].y * h) for i in _lip_indices()],
        dtype=np.float32,
    )
    corners = np.array(
        [
            (landmarks[LEFT_CORNER].x * w, landmarks[LEFT_CORNER].y * h),
            (landmarks[RIGHT_CORNER].x * w, landmarks[RIGHT_CORNER].y * h),
        ],
        dtype=np.float32,
    )
    return points, corners


def _mouth_bbox(points: np.ndarray, image_shape: tuple[int, int]) -> tuple[int, int, int, int]:
    h, w = image_shape
    x0, y0 = points.min(axis=0)
    x1, y1 = points.max(axis=0)
    mw, mh = x1 - x0, y1 - y0
    pad_x, pad_y = mw * 0.6, mh * 0.9
    x0 = max(0, int(x0 - pad_x))
    y0 = max(0, int(y0 - pad_y))
    x1 = min(w, int(x1 + pad_x))
    y1 = min(h, int(y1 + pad_y))
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


def _warp_crop(
    crop: np.ndarray,
    points_local: np.ndarray,
    corners_local: np.ndarray,
    center_y: float,
    mouth_w: float,
    mouth_h: float,
    dy_lower_frac: float,
    dy_upper_frac: float,
    dx_corner_frac: float,
) -> np.ndarray:
    if dy_lower_frac == 0 and dy_upper_frac == 0 and dx_corner_frac == 0:
        return crop.copy()

    ch, cw = crop.shape[:2]
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

    # Puntos ancla en el borde del recorte, sin desplazamiento: evita que
    # el warp distorsione mas alla de la zona de la boca.
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
    warped = tps.warpImage(crop)

    left_x, right_x = float(corners_local[0, 0]), float(corners_local[1, 0])
    warped = _paint_gap(
        warped, left_x, right_x, center_y,
        upper_amt=dy_upper_frac * mouth_h,
        lower_amt=dy_lower_frac * mouth_h,
    )
    return warped


def generate() -> None:
    settings = load_settings()
    base_rel = settings["face"]["base_image"]
    base_path = ROOT / base_rel

    image = cv2.imread(str(base_path))
    if image is None:
        raise RuntimeError(f"No pude leer la imagen base: {base_path}")

    points, corners = _detect_lip_points(image)
    bx, by, bw, bh = _mouth_bbox(points, image.shape[:2])
    crop = image[by : by + bh, bx : bx + bw]

    points_local = points - np.array([bx, by], dtype=np.float32)
    corners_local = corners - np.array([bx, by], dtype=np.float32)
    center_y = float(np.mean(corners_local[:, 1]))
    x0, y0 = points_local.min(axis=0)
    x1, y1 = points_local.max(axis=0)
    mouth_w, mouth_h = float(x1 - x0), float(y1 - y0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shapes: dict[str, str] = {}
    for name, (dy_lower, dy_upper, dx_corner) in MOUTH_SHAPES.items():
        warped = _warp_crop(
            crop, points_local, corners_local, center_y, mouth_w, mouth_h,
            dy_lower, dy_upper, dx_corner,
        )
        out_path = OUT_DIR / f"{name}.png"
        cv2.imwrite(str(out_path), warped)
        shapes[name] = f"assets/face/mouth/{name}.png"
        print(f"[face_gen] {name} -> {out_path}")

    h, w = image.shape[:2]
    manifest = {
        "base_image": base_rel[3:] if base_rel.startswith("ui/") else base_rel,
        "base_size": {"w": w, "h": h},
        "mouth_bbox": {"x": bx, "y": by, "w": bw, "h": bh},
        "mouth_shapes": shapes,
    }
    MANIFEST_PATH.write_text(
        "window.FACE_MANIFEST = " + json.dumps(manifest, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"[face_gen] manifest -> {MANIFEST_PATH}")


if __name__ == "__main__":
    generate()
