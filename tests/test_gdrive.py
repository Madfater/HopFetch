"""Google Drive link forms, the virus scan confirm page and error pages, against scripted fakes."""

from __future__ import annotations

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from downloader.providers import default_registry, gdrive
from downloader.providers.base import FileRef, LinkContext, ProviderError

FILE_ID = "1l_5RK28JRL19wpT22B-DY9We3TVXnnQQ"
START = f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download"
CONFIRM_PAGE = (
    '<!DOCTYPE html><html><head><title>Google Drive - Virus scan warning</title></head><body>'
    '<p class="uc-warning-caption">Google Drive can\'t scan this file for viruses.</p>'
    f'<span class="uc-name-size"><a href="/open?id={FILE_ID}">fcn8s_from_caffe.npz</a> (476M)</span>'
    '<form id="download-form" action="https://drive.usercontent.google.com/download" method="get">'
    '<input type="submit" id="uc-download-link" value="Download anyway"/>'
    f'<input type="hidden" name="id" value="{FILE_ID}">'
    '<input type="hidden" name="export" value="download">'
    '<input type="hidden" name="confirm" value="t">'
    '<input type="hidden" name="uuid" value="c5b64dcf-c931-4001-a34f-386e7e4ed44d"></form>'
    '</body></html>'
)
CONFIRMED = START + "&confirm=t&uuid=c5b64dcf-c931-4001-a34f-386e7e4ed44d"
QUOTA_PAGE = (
    '<html><head><title>Google Drive - Quota exceeded</title></head><body>'
    '<p class="uc-error-caption">Sorry, you can&#39;t view or download this file at this time.</p>'
    '<p class="uc-error-subcaption">Too many users have viewed or downloaded this file recently. '
    'Please try accessing the file again later.</p></body></html>'
)
DENIED_PAGE = '<html><head><title>Google Drive - Access denied</title></head><body></body></html>'
NOT_FOUND_PAGE = '<html><title>Error 404 (Not Found)!!1</title><p>The requested URL was not found.</p></html>'


def file_bytes(name: str = "fcn8s_from_caffe.npz", total: int = 498881336) -> tuple:
    return 206, {"Content-Type": "application/octet-stream",
                 "Content-Disposition": f'attachment; filename="{name}"',
                 "Content-Range": f"bytes 0-0/{total}", "Content-Length": "1"}, "x"


def page(status: int, body: str) -> tuple:
    return status, {"Content-Type": "text/html; charset=utf-8"}, body


def redirect(location: str, status: int = 302) -> tuple:
    return status, {"Location": location, "Content-Type": "text/html"}, ""


class FakeResponse:
    def __init__(self, status: int, headers: dict, body: str):
        self.status_code = status
        self.headers = CaseInsensitiveDict(headers)
        self.text = body
        self.closed = False

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeDrive:
    """Answers GETs with scripted responses in order and records each URL and its headers."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.responses = []

    def get(self, url, headers=None, allow_redirects=True, stream=False, timeout=None):
        assert allow_redirects is False
        self.requests.append((url, headers))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        resp = FakeResponse(*reply)
        self.responses.append(resp)
        return resp


@pytest.fixture
def drive(monkeypatch):
    def install(*replies):
        fake = FakeDrive(*replies)
        monkeypatch.setattr(gdrive.requests, "get", fake.get)
        return fake
    return install


def ref_for(url: str = f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing") -> FileRef:
    return default_registry().resolve(url)[1]


def context(statuses: list | None = None) -> LinkContext:
    record = statuses.append if statuses is not None else (lambda item: None)
    return LinkContext(solve_captcha=lambda image, spec: None,
                       set_status=lambda phase, key, **params: record((phase, key, params)), proxies=None)


@pytest.mark.parametrize("url", [
    f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing",
    f"https://drive.google.com/open?id={FILE_ID}",
    f"https://drive.google.com/uc?export=download&id={FILE_ID}",
    f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download&confirm=t",
])
def test_every_link_form_starts_at_the_same_download_url(drive, url):
    fake = drive(file_bytes())
    gdrive.GoogleDriveProvider().get_info(ref_for(url))
    assert fake.requests[0][0] == START
    assert fake.requests[0][1]["Range"] == "bytes=0-0"


def test_a_resource_key_is_passed_on(drive):
    fake = drive(file_bytes())
    gdrive.GoogleDriveProvider().get_info(ref_for(f"https://drive.google.com/file/d/{FILE_ID}/view?resourcekey=0-Ab_c"))
    assert fake.requests[0][0] == START + "&resourcekey=0-Ab_c"


def test_a_small_file_answers_with_its_name_and_size(drive):
    fake = drive(file_bytes("spam.txt", 5))
    info = gdrive.GoogleDriveProvider().get_info(ref_for())
    assert (info.name, info.size) == ("spam.txt", 5)
    assert fake.responses[0].closed


def test_a_utf8_file_name_is_decoded(drive):
    status, headers, body = file_bytes()
    headers["Content-Disposition"] = "attachment; filename=\"_.zip\"; filename*=UTF-8''%E6%AA%94%E6%A1%88.zip"
    drive((status, headers, body))
    assert gdrive.GoogleDriveProvider().get_info(ref_for()).name == "檔案.zip"


def test_a_large_file_goes_through_the_confirm_form(drive):
    fake = drive(page(200, CONFIRM_PAGE), file_bytes())
    info = gdrive.GoogleDriveProvider().get_info(ref_for())
    assert (info.name, info.size) == ("fcn8s_from_caffe.npz", 498881336)
    assert [url for url, _ in fake.requests] == [START, CONFIRMED]


def test_generate_links_hands_out_the_confirmed_url_per_connection(drive):
    fake = drive(page(200, CONFIRM_PAGE), file_bytes())
    statuses = []
    links = gdrive.GoogleDriveProvider().generate_links(ref_for(), 4, context(statuses))
    assert links == [CONFIRMED] * 4
    assert statuses == [("links", "messages.links_generated", {"done": 4, "count": 4})]
    assert all(resp.closed for resp in fake.responses)


def test_redirects_between_drive_hosts_are_followed(drive):
    fake = drive(redirect("https://drive.google.com/uc?id=x", 303), file_bytes())
    gdrive.GoogleDriveProvider().get_info(ref_for())
    assert fake.requests[1][0] == "https://drive.google.com/uc?id=x"


def test_a_redirect_elsewhere_is_not_followed(drive):
    fake = drive(redirect("https://evil.test/x"))
    with pytest.raises(ProviderError) as info:
        gdrive.GoogleDriveProvider().get_info(ref_for())
    assert info.value.code == "upstream_error" and len(fake.requests) == 1


def test_a_second_confirm_page_is_not_followed_again(drive):
    fake = drive(page(200, CONFIRM_PAGE), page(200, CONFIRM_PAGE))
    with pytest.raises(ProviderError) as info:
        gdrive.GoogleDriveProvider().get_info(ref_for())
    assert info.value.code == "upstream_error" and len(fake.requests) == 2


def test_a_confirm_form_posting_off_drive_is_not_followed(drive):
    fake = drive(page(200, CONFIRM_PAGE.replace("drive.usercontent.google.com", "evil.test")))
    with pytest.raises(ProviderError):
        gdrive.GoogleDriveProvider().get_info(ref_for())
    assert len(fake.requests) == 1


@pytest.mark.parametrize("replies,code", [
    ([page(404, NOT_FOUND_PAGE)], "not_found"),
    ([redirect("https://accounts.google.com/ServiceLogin?continue=x")], "private"),
    ([page(403, DENIED_PAGE)], "private"),
    ([page(200, DENIED_PAGE)], "private"),
    ([(401, {"Content-Type": "application/json"}, "{}")], "private"),
    ([page(403, QUOTA_PAGE)], "quota_exceeded"),
    ([page(200, CONFIRM_PAGE), page(200, QUOTA_PAGE)], "quota_exceeded"),
    ([page(200, "<html><title>Something else</title></html>")], "upstream_error"),
    ([(500, {"Content-Type": "application/octet-stream"}, "")], "upstream_error"),
    ([requests.ConnectionError()], "upstream_error"),
])
def test_drive_answers_map_to_codes(drive, replies, code):
    drive(*replies)
    with pytest.raises(ProviderError) as info:
        gdrive.GoogleDriveProvider().get_info(ref_for())
    assert info.value.code == code
    if code in ("quota_exceeded", "upstream_error"):
        assert info.value.params == {"provider": "Google Drive"}


def test_generate_links_reports_errors_too(drive):
    drive(page(200, QUOTA_PAGE))
    with pytest.raises(ProviderError) as info:
        gdrive.GoogleDriveProvider().generate_links(ref_for(), 2, context())
    assert info.value.code == "quota_exceeded"
