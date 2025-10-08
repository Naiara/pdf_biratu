import fitz
import pytesseract
from PIL import Image
import io
import cv2
import numpy as np


def detect_page_rotation_from_image(pil_image: Image.Image) -> int:
    """Return orientation in degrees from Tesseract OSD (0/90/180/270)."""
    try:
        osd = pytesseract.image_to_osd(pil_image)
        for line in osd.splitlines():
            if 'Orientation in degrees' in line:
                deg = int(line.split(':')[-1].strip())
                return deg % 360
    except Exception:
        pass
    return 0


def detect_rotations(input_pdf_path: str, dpi: int = 200):
    """Return a list with detected orientation (degrees) and suggested rotation per page.

    Each item: {page: i, detected_deg: deg, rotate_clockwise: rotate, needs_rotation: bool}
    """
    doc = fitz.open(input_pdf_path)
    results = []

    # Use the top-level decision helper for consistency
    for i in range(doc.page_count):
        page = doc.load_page(i)
        # render at higher DPI for better OCR/visual quality
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img_bytes = pix.tobytes('png')
        pil_img = Image.open(io.BytesIO(img_bytes))

        # original osd for diagnostics
        detected_deg = detect_page_rotation_from_image(pil_img)
        rotate_clockwise = decide_clockwise_rotation(pil_img)
        needs = (rotate_clockwise != 0)

        results.append({
            'page': i + 1,
            'detected_deg': int(detected_deg),
            'rotate_clockwise': int(rotate_clockwise),
            'needs_rotation': bool(needs),
        })

    # (single loop above already populated results)

    doc.close()
    return results


def detect_rotation_cv(pil_image: Image.Image) -> int | None:
    """
    Rough fallback using OpenCV: detect dominant line angles and infer page rotation.
    Returns 0/90/180/270 or None if uncertain.
    """
    # convert to grayscale numpy array
    img = np.array(pil_image.convert('L'))
    # resize to speed up
    h, w = img.shape
    scale = 800 / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    # edge detection
    edges = cv2.Canny(img, 50, 150)
    # Hough lines
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=200)
    if lines is None:
        return None
    angles = []
    for rho_theta in lines[:200]:
        rho, theta = rho_theta[0]
        angle = theta * 180 / np.pi
        # convert to degrees relative to horizontal
        angles.append(angle)

    if len(angles) == 0:
        return None

    # map angles to [-90,90]
    angles = [((a + 90) % 180) - 90 for a in angles]
    median_angle = np.median(angles)

    # If median_angle close to 90 or -90 means rotated 90 deg
    # Convert to required rotation to make text horizontal
    # If median_angle near 0 => no rotation
    if abs(median_angle) < 10:
        return 0
    if 80 < abs(median_angle) <= 100:
        # roughly vertical lines -> page likely rotated 90 or 270
        # decide based on sign
        if median_angle > 0:
            return 270
        else:
            return 90
    # if moderately tilted, round to nearest 90
    rounded = int(round(median_angle / 90.0) * 90) % 360
    if rounded in (0, 90, 180, 270):
        return rounded
    return None


def decide_clockwise_rotation(pil_img: Image.Image) -> int:
    """Top-level helper to decide clockwise rotation (0/90/180/270) for an image.

    Uses Tesseract OSD, CV fallback and OCR-rotation test similar to the other helpers.
    """
    try:
        osd_deg = detect_page_rotation_from_image(pil_img)
    except Exception:
        osd_deg = 0

    candidate_from_osd = (360 - osd_deg) % 360 if osd_deg != 0 else 0
    try:
        deg_cv = detect_rotation_cv(pil_img)
        candidate_from_cv = (360 - deg_cv) % 360 if deg_cv is not None and deg_cv != 0 else 0 if deg_cv == 0 else None
    except Exception:
        candidate_from_cv = None

    if osd_deg != 0 and candidate_from_cv is not None and candidate_from_cv == candidate_from_osd:
        return int(candidate_from_osd)

    # OCR-based verification: rotate CCW candidates and pick the one with most text
    try:
        scores = []
        for ccw in (0, 90, 180, 270):
            test_img = pil_img.rotate(ccw, expand=True)
            try:
                txt = pytesseract.image_to_string(test_img)
            except Exception:
                txt = ''
            l = len(txt.strip())
            scores.append((ccw, l))

        # choose best and second best to apply a confidence rule
        scores.sort(key=lambda x: x[1], reverse=True)
        best_ccw, best_len = scores[0]
        second_len = scores[1][1] if len(scores) > 1 else 0

        # decide only if there's enough text and best is significantly better than second
        if best_len >= 20 and (second_len == 0 or best_len >= 1.5 * second_len):
            return int((360 - best_ccw) % 360)
    except Exception:
        pass

    if candidate_from_osd is not None:
        return int(candidate_from_osd)
    if candidate_from_cv is not None:
        return int(candidate_from_cv)
    return 0


def fix_pdf_rotation(input_pdf_path: str, output_pdf_path: str, dpi: int = 200) -> bool:
    """
    Rebuild the PDF by rendering each page to an image, rotating the image when
    needed (using the combined detection logic), and inserting the corrected
    image into a new PDF. This guarantees the visual orientation is fixed.

    Returns True if any page was changed.
    """
    src = fitz.open(input_pdf_path)
    new_doc = fitz.open()
    changed = False

    # use top-level decide_clockwise_rotation for consistency

    for i in range(src.page_count):
        page = src.load_page(i)
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img_bytes = pix.tobytes('png')
        pil_img = Image.open(io.BytesIO(img_bytes))

        rotate_clockwise = decide_clockwise_rotation(pil_img)
        if rotate_clockwise != 0:
            # Convert clockwise rotation to CCW degrees for PIL.rotate
            rotate_ccw = (360 - rotate_clockwise) % 360
            pil_img = pil_img.rotate(rotate_ccw, expand=True)
            changed = True

        # convert back to PNG bytes
        out_buf = io.BytesIO()
        pil_img.save(out_buf, format='PNG')
        img_data = out_buf.getvalue()

        # create a new page in the output PDF with the image filling the page
        new_page = new_doc.new_page(width=pil_img.width, height=pil_img.height)
        new_page.insert_image(new_page.rect, stream=img_data)

    if not changed:
        src.close()
        new_doc.close()
        return False

    new_doc.save(output_pdf_path)
    src.close()
    new_doc.close()
    return True


def export_rotated_images_zip(input_pdf_path: str, output_zip_path: str, image_format: str = 'PNG', dpi: int = 200) -> bool:
    """
    Render each page, rotate the page image if needed and write images into a ZIP file.
    Returns True if at least one page was processed (zip created).
    """
    src = fitz.open(input_pdf_path)
    import zipfile

    if src.page_count == 0:
        src.close()
        return False

    with zipfile.ZipFile(output_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(src.page_count):
            page = src.load_page(i)
            matrix = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_bytes = pix.tobytes('png')
            pil_img = Image.open(io.BytesIO(img_bytes))

            rotate_clockwise = decide_clockwise_rotation(pil_img)
            if rotate_clockwise != 0:
                rotate_ccw = (360 - rotate_clockwise) % 360
                pil_img = pil_img.rotate(rotate_ccw, expand=True)

            out_buf = io.BytesIO()
            # For PNG we keep transparency handling consistent; JPEG could be supported
            save_kwargs = {}
            if image_format.upper() in ('JPEG', 'JPG'):
                save_kwargs['quality'] = 85
                pil_img = pil_img.convert('RGB')

            pil_img.save(out_buf, format=image_format, **save_kwargs)
            img_data = out_buf.getvalue()
            name = f'page_{i+1}.{image_format.lower()}'
            zf.writestr(name, img_data)

    src.close()
    return True
