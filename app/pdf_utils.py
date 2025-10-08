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


def detect_rotations(input_pdf_path: str):
    """Return a list with detected orientation (degrees) and suggested rotation per page.

    Each item: {page: i, detected_deg: deg, rotate_clockwise: rotate, needs_rotation: bool}
    """
    doc = fitz.open(input_pdf_path)
    results = []

    def choose_rotation_to_apply(pil_img: Image.Image) -> int:
        """
        Decide a final rotation to apply in clockwise degrees (0/90/180/270).
        Strategy:
        1. Try Tesseract OSD.
        2. If OSD returns 0, try CV fallback.
        3. If OSD and CV disagree or are uncertain, run a small OCR-based test:
           rotate the page by candidate CCW angles (0/90/180/270) and pick the one
           that yields the most OCR text; convert that to a clockwise rotation to apply.
        Returns clockwise degrees to rotate the page so it becomes upright.
        """

        # 1) OSD
        try:
            osd_deg = detect_page_rotation_from_image(pil_img)
        except Exception:
            osd_deg = 0

        # osd_deg is orientation in degrees (0/90/180/270) representing how the
        # page content is currently rotated clockwise. To correct it we would
        # rotate clockwise by (360 - osd_deg) % 360. We'll use that as candidate.
        candidate_from_osd = (360 - osd_deg) % 360 if osd_deg != 0 else 0

        # 2) CV fallback (only if OSD says 0 or low confidence)
        candidate_from_cv = None
        try:
            deg_cv = detect_rotation_cv(pil_img)
            if deg_cv is not None:
                candidate_from_cv = (360 - deg_cv) % 360 if deg_cv != 0 else 0
        except Exception:
            candidate_from_cv = None

        # If OSD gave a non-zero answer and CV agrees -> accept.
        if osd_deg != 0 and candidate_from_cv is not None and candidate_from_cv == candidate_from_osd:
            return int(candidate_from_osd)

        # 3) OCR-based verification: rotate image by CCW angles 0/90/180/270 and
        # choose the rotation that yields the most OCR text (heuristic).
        try:
            best_ccw = None
            best_len = -1
            for ccw in (0, 90, 180, 270):
                test_img = pil_img.rotate(ccw, expand=True)
                try:
                    txt = pytesseract.image_to_string(test_img)
                except Exception:
                    txt = ''
                l = len(txt.strip())
                if l > best_len:
                    best_len = l
                    best_ccw = ccw

            if best_ccw is not None:
                # best_ccw is the CCW degrees we should apply to make the page upright
                # convert to clockwise rotation to apply
                final_clockwise = (360 - best_ccw) % 360
                return int(final_clockwise)
        except Exception:
            pass

        # fallback: prefer OSD candidate if present, else CV candidate, else 0
        if candidate_from_osd is not None:
            return int(candidate_from_osd)
        if candidate_from_cv is not None:
            return int(candidate_from_cv)
        return 0

    for i in range(doc.page_count):
        page = doc.load_page(i)
        pix = page.get_pixmap(alpha=False)
        img_bytes = pix.tobytes('png')
        pil_img = Image.open(io.BytesIO(img_bytes))

        # original osd for diagnostics
        detected_deg = detect_page_rotation_from_image(pil_img)
        rotate_clockwise = choose_rotation_to_apply(pil_img)
        needs = (rotate_clockwise != 0)

        results.append({
            'page': i + 1,
            'detected_deg': int(detected_deg),
            'rotate_clockwise': int(rotate_clockwise),
            'needs_rotation': bool(needs),
        })

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


def fix_pdf_rotation(input_pdf_path: str, output_pdf_path: str) -> bool:
    """
    Rebuild the PDF by rendering each page to an image, rotating the image when
    needed (using the combined detection logic), and inserting the corrected
    image into a new PDF. This guarantees the visual orientation is fixed.

    Returns True if any page was changed.
    """
    src = fitz.open(input_pdf_path)
    new_doc = fitz.open()
    changed = False

    # helper to decide final rotation (clockwise degrees) for a PIL image
    def decide_clockwise_rotation(pil_img: Image.Image) -> int:
        # prefer the same logic used in detect_rotations: try OSD, CV, then OCR-test
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

        # quick agreement
        if osd_deg != 0 and candidate_from_cv is not None and candidate_from_cv == candidate_from_osd:
            return int(candidate_from_osd)

        # OCR-based verification
        try:
            best_ccw = None
            best_len = -1
            for ccw in (0, 90, 180, 270):
                test_img = pil_img.rotate(ccw, expand=True)
                try:
                    txt = pytesseract.image_to_string(test_img)
                except Exception:
                    txt = ''
                l = len(txt.strip())
                if l > best_len:
                    best_len = l
                    best_ccw = ccw
            if best_ccw is not None:
                return int((360 - best_ccw) % 360)
        except Exception:
            pass

        if candidate_from_osd is not None:
            return int(candidate_from_osd)
        if candidate_from_cv is not None:
            return int(candidate_from_cv)
        return 0

    for i in range(src.page_count):
        page = src.load_page(i)
        pix = page.get_pixmap(alpha=False)
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
