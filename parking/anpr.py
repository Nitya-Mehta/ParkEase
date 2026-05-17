import base64
import binascii
import re
from functools import lru_cache
from time import perf_counter
from uuid import uuid4

from django.core.files.base import ContentFile

cv2 = None
np = None


def get_cv2():
    global cv2
    if cv2 is None:
        import cv2 as cv2_module
        cv2 = cv2_module
    return cv2


def get_np():
    global np
    if np is None:
        import numpy as np_module
        np = np_module
    return np


PLATE_TEXT_RE = re.compile(r'[^A-Z0-9]+')
INDIAN_PLATE_PATTERNS = (
    re.compile(r'^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$'),
    re.compile(r'^[A-Z]{2}\d{2}[A-Z]{2}\d{4}$'),
)


def normalize_plate_text(value):
    return PLATE_TEXT_RE.sub('', (value or '').upper())


def decode_scan_image(uploaded_file=None, captured_image_data=''):
    if uploaded_file:
        return uploaded_file.read(), uploaded_file.name or f'scan-{uuid4().hex}.jpg'

    if not captured_image_data:
        return None, None

    try:
        header, encoded = captured_image_data.split(',', 1)
    except ValueError:
        encoded = captured_image_data
        header = 'data:image/jpeg;base64'

    extension = 'jpg'
    if 'png' in header.lower():
        extension = 'png'

    try:
        image_bytes = base64.b64decode(encoded)
    except (ValueError, binascii.Error):
        return None, None
    return image_bytes, f'camera-scan-{uuid4().hex}.{extension}'


def build_content_file(image_bytes, filename):
    return ContentFile(image_bytes, name=filename)


@lru_cache(maxsize=1)
def get_ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def decode_cv_image(image_bytes):
    cv2_local = get_cv2()
    np_local = get_np()
    image_array = np_local.frombuffer(image_bytes, dtype=np_local.uint8)
    return cv2_local.imdecode(image_array, cv2_local.IMREAD_COLOR)


def encode_image_data_uri(image):
    cv2_local = get_cv2()
    success, buffer = cv2_local.imencode('.jpg', image)
    if not success:
        return None
    encoded = base64.b64encode(buffer.tobytes()).decode('ascii')
    return f'data:image/jpeg;base64,{encoded}'


def resize_for_ocr(image):
    height, width = image.shape[:2]
    scale = 1.0
    if width < 960:
        scale = 960 / float(width)
    elif width > 1600:
        scale = 1600 / float(width)

    if abs(scale - 1.0) < 0.01:
        return image, 1.0

    cv2_local = get_cv2()
    resized = cv2_local.resize(image, None, fx=scale, fy=scale, interpolation=cv2_local.INTER_CUBIC if scale > 1 else cv2_local.INTER_AREA)
    return resized, scale


def ensure_bgr(image):
    cv2_local = get_cv2()
    if len(image.shape) == 2:
        return cv2_local.cvtColor(image, cv2_local.COLOR_GRAY2BGR)
    return image


def build_ocr_variants(image):
    cv2_local = get_cv2()
    gray = cv2_local.cvtColor(image, cv2_local.COLOR_BGR2GRAY)
    clahe = cv2_local.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    enhanced_gray = clahe.apply(gray)
    bilateral = cv2_local.bilateralFilter(enhanced_gray, 9, 75, 75)
    thresh = cv2_local.adaptiveThreshold(
        bilateral,
        255,
        cv2_local.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2_local.THRESH_BINARY,
        31,
        9,
    )
    blackhat_kernel = cv2_local.getStructuringElement(cv2_local.MORPH_RECT, (25, 7))
    blackhat = cv2_local.morphologyEx(gray, cv2_local.MORPH_BLACKHAT, blackhat_kernel)
    sharpen = cv2_local.addWeighted(enhanced_gray, 1.5, cv2_local.GaussianBlur(enhanced_gray, (0, 0), 3), -0.5, 0)

    return [
        ('original', image),
        ('enhanced', ensure_bgr(enhanced_gray)),
        ('bilateral', ensure_bgr(bilateral)),
        ('threshold', ensure_bgr(thresh)),
        ('blackhat', ensure_bgr(blackhat)),
        ('sharpen', ensure_bgr(sharpen)),
    ]


def run_ocr(image):
    engine = get_ocr_engine()
    results, _ = engine(image, use_det=True, use_cls=True, use_rec=True, text_score=0.25)
    return results or []


def polygon_to_bbox(points):
    cv2_local = get_cv2()
    np_local = get_np()
    contour = np_local.array(points, dtype=np_local.float32)
    x, y, w, h = cv2_local.boundingRect(contour.astype(np_local.int32))
    return {'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)}


def offset_bbox(bbox, offset_x=0, offset_y=0):
    return {
        'x': int(bbox['x'] + offset_x),
        'y': int(bbox['y'] + offset_y),
        'w': int(bbox['w']),
        'h': int(bbox['h']),
    }


def union_bboxes(boxes):
    x1 = min(box['x'] for box in boxes)
    y1 = min(box['y'] for box in boxes)
    x2 = max(box['x'] + box['w'] for box in boxes)
    y2 = max(box['y'] + box['h'] for box in boxes)
    return {'x': int(x1), 'y': int(y1), 'w': int(x2 - x1), 'h': int(y2 - y1)}


def aspect_ratio_for_bbox(bbox):
    return bbox['w'] / float(max(bbox['h'], 1))


def score_plate_candidate(normalized_text, bbox, ocr_score, expected_plates=None):
    expected_plates = expected_plates or set()
    if not normalized_text:
        return -999.0

    length = len(normalized_text)
    digits = sum(character.isdigit() for character in normalized_text)
    letters = sum(character.isalpha() for character in normalized_text)
    area = bbox['w'] * bbox['h']
    aspect_ratio = aspect_ratio_for_bbox(bbox)

    score = float(ocr_score) * 3.0
    if 6 <= length <= 12:
        score += 1.0
    else:
        score -= 2.5

    if digits >= 2 and letters >= 2:
        score += 1.4
    else:
        score -= 1.5

    if any(pattern.match(normalized_text) for pattern in INDIAN_PLATE_PATTERNS):
        score += 4.8
    elif re.match(r'^[A-Z]{2}\d{1,2}[A-Z0-9]{1,4}\d{4}$', normalized_text):
        score += 2.6
    elif re.match(r'^[A-Z0-9]{6,12}$', normalized_text):
        score += 0.6

    if 2.0 <= aspect_ratio <= 6.5:
        score += 0.8
    elif 1.4 <= aspect_ratio <= 8.0:
        score += 0.2

    if area >= 2500:
        score += 0.4

    if normalized_text in expected_plates:
        score += 5.5

    return score


def build_candidate(text, bbox, ocr_score, expected_plates=None, source='ocr'):
    normalized_text = normalize_plate_text(text)
    if not normalized_text:
        return None

    return {
        'text': text.strip(),
        'normalized_text': normalized_text,
        'bounding_box': bbox,
        'ocr_score': float(ocr_score),
        'score': score_plate_candidate(normalized_text, bbox, ocr_score, expected_plates=expected_plates),
        'source': source,
    }


def combine_line_candidates(entries, expected_plates=None, source='ocr-line'):
    groups = []
    for entry in sorted(entries, key=lambda item: (item['center_y'], item['bounding_box']['x'])):
        matched_group = None
        for group in groups:
            if abs(entry['center_y'] - group['center_y']) <= max(entry['height'], group['height']) * 0.65:
                matched_group = group
                break
        if matched_group is None:
            groups.append({
                'entries': [entry],
                'center_y': entry['center_y'],
                'height': entry['height'],
            })
            continue

        matched_group['entries'].append(entry)
        matched_group['center_y'] = (matched_group['center_y'] + entry['center_y']) / 2.0
        matched_group['height'] = max(matched_group['height'], entry['height'])

    combined = []
    for group in groups:
        line_entries = sorted(group['entries'], key=lambda item: item['bounding_box']['x'])
        normalized_text = ''.join(item['normalized_text'] for item in line_entries)
        if len(normalized_text) < 6:
            continue
        bbox = union_bboxes([item['bounding_box'] for item in line_entries])
        avg_score = sum(item['ocr_score'] for item in line_entries) / len(line_entries)
        candidate = build_candidate(
            normalized_text,
            bbox,
            avg_score,
            expected_plates=expected_plates,
            source=source,
        )
        if candidate:
            combined.append(candidate)
    return combined


def extract_candidates_from_ocr(ocr_results, expected_plates=None, offset_x=0, offset_y=0, source='ocr'):
    expected_plates = expected_plates or set()
    entries = []
    candidates = []

    for result in ocr_results:
        if len(result) < 3:
            continue
        box_points, text, confidence = result[:3]
        bbox = offset_bbox(polygon_to_bbox(box_points), offset_x=offset_x, offset_y=offset_y)
        normalized_text = normalize_plate_text(text)
        if not normalized_text:
            continue
        entry = {
            'text': text.strip(),
            'normalized_text': normalized_text,
            'bounding_box': bbox,
            'ocr_score': float(confidence),
            'center_y': bbox['y'] + (bbox['h'] / 2.0),
            'height': bbox['h'],
        }
        entries.append(entry)
        candidate = build_candidate(
            text,
            bbox,
            confidence,
            expected_plates=expected_plates,
            source=source,
        )
        if candidate:
            candidates.append(candidate)

    candidates.extend(combine_line_candidates(entries, expected_plates=expected_plates, source=f'{source}-line'))
    return candidates


def dedupe_candidates(candidates):
    best_by_text = {}
    for candidate in candidates:
        text_key = candidate['normalized_text']
        if text_key not in best_by_text or candidate['score'] > best_by_text[text_key]['score']:
            best_by_text[text_key] = candidate
    return sorted(best_by_text.values(), key=lambda item: item['score'], reverse=True)


def find_plate_candidate_boxes(image):
    cv2_local = get_cv2()
    np_local = get_np()
    gray = cv2_local.cvtColor(image, cv2_local.COLOR_BGR2GRAY)
    gray = cv2_local.GaussianBlur(gray, (5, 5), 0)

    rect_kernel = cv2_local.getStructuringElement(cv2_local.MORPH_RECT, (25, 7))
    sq_kernel = cv2_local.getStructuringElement(cv2_local.MORPH_RECT, (5, 5))

    blackhat = cv2_local.morphologyEx(gray, cv2_local.MORPH_BLACKHAT, rect_kernel)
    grad_x = cv2_local.Sobel(blackhat, cv2_local.CV_32F, 1, 0, ksize=-1)
    grad_x = np_local.absolute(grad_x)
    min_val = float(grad_x.min())
    max_val = float(grad_x.max())
    if max_val - min_val > 0:
        grad_x = ((grad_x - min_val) / (max_val - min_val) * 255).astype('uint8')
    else:
        grad_x = np_local.zeros_like(gray)

    grad_x = cv2_local.morphologyEx(grad_x, cv2_local.MORPH_CLOSE, rect_kernel)
    thresh = cv2_local.threshold(grad_x, 0, 255, cv2_local.THRESH_BINARY | cv2_local.THRESH_OTSU)[1]
    thresh = cv2_local.morphologyEx(thresh, cv2_local.MORPH_CLOSE, sq_kernel, iterations=2)
    thresh = cv2_local.erode(thresh, None, iterations=1)
    thresh = cv2_local.dilate(thresh, None, iterations=2)

    contours, _ = cv2_local.findContours(thresh, cv2_local.RETR_EXTERNAL, cv2_local.CHAIN_APPROX_SIMPLE)
    boxes = []
    image_area = image.shape[0] * image.shape[1]

    for contour in sorted(contours, key=cv2_local.contourArea, reverse=True)[:20]:
        x, y, w, h = cv2_local.boundingRect(contour)
        area = w * h
        aspect_ratio = w / float(max(h, 1))
        if area < image_area * 0.002:
            continue
        if not 2.0 <= aspect_ratio <= 7.5:
            continue
        boxes.append({'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)})

    deduped = []
    for box in boxes:
        overlap = False
        for existing in deduped:
            dx = abs(existing['x'] - box['x'])
            dy = abs(existing['y'] - box['y'])
            if dx < 20 and dy < 20:
                overlap = True
                break
        if not overlap:
            deduped.append(box)
    return deduped[:8]


def crop_with_padding(image, bbox, padding_ratio=0.12):
    height, width = image.shape[:2]
    pad_x = int(bbox['w'] * padding_ratio)
    pad_y = int(bbox['h'] * padding_ratio)
    x1 = max(0, bbox['x'] - pad_x)
    y1 = max(0, bbox['y'] - pad_y)
    x2 = min(width, bbox['x'] + bbox['w'] + pad_x)
    y2 = min(height, bbox['y'] + bbox['h'] + pad_y)
    return image[y1:y2, x1:x2], x1, y1


def map_bbox_to_original(bbox, scale):
    if not bbox:
        return {}
    if not scale or abs(scale - 1.0) < 0.01:
        return bbox
    return {
        'x': int(round(bbox['x'] / scale)),
        'y': int(round(bbox['y'] / scale)),
        'w': int(round(bbox['w'] / scale)),
        'h': int(round(bbox['h'] / scale)),
    }


def select_best_candidate(candidates):
    if not candidates:
        return None
    return max(candidates, key=lambda item: item['score'])


def annotate_detection(image, bbox):
    cv2_local = get_cv2()
    annotated = image.copy()
    if bbox:
        x = bbox['x']
        y = bbox['y']
        w = bbox['w']
        h = bbox['h']
        cv2_local.rectangle(annotated, (x, y), (x + w, y + h), (43, 57, 109), 3)
    return annotated


def crop_from_bbox(image, bbox):
    if not bbox:
        return None
    x = max(0, bbox['x'])
    y = max(0, bbox['y'])
    w = max(1, bbox['w'])
    h = max(1, bbox['h'])
    return image[y:y + h, x:x + w]


def detect_plate_region(image_bytes, expected_plates=None):
    original_image = decode_cv_image(image_bytes)
    if original_image is None:
        return None

    expected_plates = {normalize_plate_text(value) for value in (expected_plates or set()) if normalize_plate_text(value)}

    working_image, scale = resize_for_ocr(original_image)
    started_at = perf_counter()
    candidates = []

    for variant_name, variant_image in build_ocr_variants(working_image):
        ocr_results = run_ocr(variant_image)
        candidates.extend(
            extract_candidates_from_ocr(
                ocr_results,
                expected_plates=expected_plates,
                source=f'full-{variant_name}',
            )
        )

    candidates = dedupe_candidates(candidates)
    best_candidate = select_best_candidate(candidates)

    if best_candidate is None or best_candidate['score'] < 6.0:
        for index, crop_box in enumerate(find_plate_candidate_boxes(working_image)):
            crop_image, offset_x, offset_y = crop_with_padding(working_image, crop_box)
            if crop_image.size == 0:
                continue
            for variant_name, variant_image in build_ocr_variants(crop_image):
                ocr_results = run_ocr(variant_image)
                candidates.extend(
                    extract_candidates_from_ocr(
                        ocr_results,
                        expected_plates=expected_plates,
                        offset_x=offset_x,
                        offset_y=offset_y,
                        source=f'crop-{index}-{variant_name}',
                    )
                )
        candidates = dedupe_candidates(candidates)
        best_candidate = select_best_candidate(candidates)

    mapped_bbox = map_bbox_to_original(best_candidate['bounding_box'], scale) if best_candidate else {}
    annotated_image = annotate_detection(original_image, mapped_bbox)
    plate_crop = crop_from_bbox(original_image, mapped_bbox)
    processing_ms = int((perf_counter() - started_at) * 1000)

    return {
        'bounding_box': mapped_bbox,
        'annotated_image': encode_image_data_uri(annotated_image),
        'plate_crop_image': encode_image_data_uri(plate_crop) if plate_crop is not None and plate_crop.size else None,
        'confidence': round(min(0.99, max(0.0, best_candidate['ocr_score'] if best_candidate else 0.0)), 2),
        'plate_text': best_candidate['normalized_text'] if best_candidate else '',
        'raw_text': best_candidate['text'] if best_candidate else '',
        'processing_ms': processing_ms,
        'candidates': [
            {
                'text': candidate['normalized_text'],
                'score': round(candidate['score'], 2),
                'source': candidate['source'],
            }
            for candidate in candidates[:5]
        ],
    }
