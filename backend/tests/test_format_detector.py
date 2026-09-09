from app.format_detector import detect_format


def test_csv_by_extension_and_content():
    assert detect_format("games.csv", b"app_id,name\n1,Foo\n") == "csv"


def test_json_by_extension_and_content():
    assert detect_format("games.json", b'{"1": {"name": "Foo"}}') == "json"


def test_json_array_by_extension_and_content():
    assert detect_format("games.json", b'[{"name": "Foo"}]') == "json"


def test_xlsx_by_zip_signature_regardless_of_extension():
    # A real .xlsx is a zip archive - PK\x03\x04 is the zip local-file-header magic.
    assert detect_format("games.dat", b"PK\x03\x04rest-of-a-real-xlsx-file") == "xlsx"


def test_wrong_extension_falls_back_to_content_sniffing():
    # Claims .xlsx but is actually JSON text - pd.read_excel can't parse non-zip
    # bytes at all (unlike read_csv, which is lenient enough to "succeed" on almost
    # any single-column text), so this reliably exercises the fallback path: the
    # extension is trusted only if the content really parses as that format.
    assert detect_format("games.xlsx", b'{"1": {"name": "Foo"}}') == "json"


def test_pdf_detected_and_reported_honestly():
    assert detect_format("report.pdf", b"%PDF-1.4 rest of file") == "pdf"


def test_jpg_detected_and_reported_honestly():
    assert detect_format("screenshot.jpg", b"\xff\xd8\xffrest of jpeg bytes") == "jpg"


def test_png_detected_and_reported_honestly():
    assert detect_format("image.png", b"\x89PNG\r\n\x1a\nrest") == "png"


def test_unrecognized_binary_defaults_to_csv():
    # Not a documented contract so much as the current fallback behavior - pinned
    # here so a change to it is a deliberate decision, not an accident.
    assert detect_format("mystery.bin", b"\x00\x01\x02\x03garbage") == "csv"
