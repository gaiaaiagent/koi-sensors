"""Tests for the newsletters sensor: post URLs, tracking links, watermark
retries, account-mail skips and config (koi-sensors#13)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SENSOR_DIR = REPO / "sensors" / "newsletters"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SENSOR_DIR))

spec = importlib.util.spec_from_file_location("newsletters_sensor_module", SENSOR_DIR / "newsletters_sensor.py")
assert spec and spec.loader
ns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ns)

from shared.persistent_state import PersistentSensorState  # noqa: E402

PIXEL = "https://eotrx.substackcdn.com/open?token=PIXELTOKEN&tracking_id=abc"
TITLE_LINK = "https://open.substack.com/pub/natesnewsletter/p/my-post?utm_source=post-email-title&utm_campaign=email-post-title&r=SUBSCRIBER&token=TITLETOKEN"
REDIRECT = "https://substack.com/redirect/2/eyJlIjoiaHR0cHM6Ly9leGFtcGxlLmNvbSJ9.SIG?j=JWTTOKEN"
APP_LINK = "https://substack.com/app-link/post?publication_id=1&post_id=2&utm_source=post-email-title&token=APPTOKEN"
UNSUB = "https://natesnewsletter.substack.com/action/disable_email?token=UNSUBTOKEN"
IMAGE = (
    "https://substackcdn.com/image/fetch/$s_!x!,w_1456,c_limit,f_auto/"
    "https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fpublic%2Fimages%2Fchart.png"
)
EXTERNAL = "https://github.com/org/repo/pull/7?utm_source=newsletter&tab=files&token=EXTTOKEN"
SECRETS = ("PIXELTOKEN", "SUBSCRIBER", "TITLETOKEN", "JWTTOKEN", "APPTOKEN", "UNSUBTOKEN", "EXTTOKEN")


def newsletter_html(slug: str = "my-post", extra: str = "") -> str:
    title_link = TITLE_LINK.replace("my-post", slug)
    body = " ".join(["Agents need a written record of what they did and why."] * 12)
    return f"""<html><body>
<img src="{PIXEL}" width="1" height="1">
<h1><a href="{title_link}">My Post</a></h1>
<p><a href="{APP_LINK}">READ IN APP</a></p>
<p>{body}</p>
<p>See <a href="{REDIRECT}">this example</a> and <a href="{EXTERNAL}">the PR</a>.</p>
<p><img src="{IMAGE}" alt="chart"></p>
{extra}
<p><a href="{UNSUB}">Unsubscribe</a></p>
</body></html>"""


def raw_email(uid: int, subject: str = "My Post", slug: str = "my-post",
              sender: str = "natesnewsletter@substack.com") -> bytes:
    msg = EmailMessage()
    msg["From"] = f"Nate <{sender}>"
    msg["To"] = "sensor@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = f"<post-{uid}@substack.com>"
    msg["Date"] = format_datetime(datetime.now(timezone.utc) - timedelta(days=1))
    msg.set_content("plain text fallback " * 20)
    msg.add_alternative(newsletter_html(slug), subtype="html")
    return msg.as_bytes()


# --- post URL --------------------------------------------------------------

def test_canonical_url_skips_the_pixel_and_drops_the_query() -> None:
    html = newsletter_html()
    assert ns._canonical_post_url(html, publication="natesnewsletter") == \
        "https://natesnewsletter.substack.com/p/my-post"


def test_canonical_url_prefers_the_sending_publication() -> None:
    html = ('<a href="https://other.substack.com/p/recommended">x</a>'
            '<a href="https://natesnewsletter.substack.com/p/the-post?r=abc">y</a>')
    assert ns._canonical_post_url(html, publication="natesnewsletter") == \
        "https://natesnewsletter.substack.com/p/the-post"
    assert ns._canonical_post_url(html) == "https://other.substack.com/p/recommended"


def test_canonical_url_is_empty_without_a_post_link() -> None:
    assert ns._canonical_post_url(f'<img src="{PIXEL}"><a href="{REDIRECT}">x</a>') == ""


def test_publication_hint_comes_from_the_substack_sender() -> None:
    assert ns._publication_hint("natesnewsletter@substack.com") == "natesnewsletter"
    assert ns._publication_hint("someone@example.com") == ""


# --- tracking links ----------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    (PIXEL, None),
    (REDIRECT, None),
    (APP_LINK, None),
    (UNSUB, None),
    ("https://natesnewsletter.substack.com/account?token=X", None),
    (TITLE_LINK, "https://natesnewsletter.substack.com/p/my-post"),
    ("https://natesnewsletter.substack.com/subscribe?utm_source=x&r=SUB", "https://natesnewsletter.substack.com/subscribe"),
    (IMAGE, "https://substack-post-media.s3.amazonaws.com/public/images/chart.png"),
    (EXTERNAL, "https://github.com/org/repo/pull/7?tab=files"),
    ("https://example.com/page?id=3#part", "https://example.com/page?id=3#part"),
])
def test_clean_url(url: str, expected) -> None:
    assert ns._clean_url(url) == expected


def test_strip_tracking_on_html2text_output() -> None:
    text = ns._strip_tracking(ns._strip_html_to_text(newsletter_html()))
    for secret in SECRETS:
        assert secret not in text
    for marker in ("eotrx", "substack.com/redirect", "app-link", "disable_email", "token="):
        assert marker not in text
    assert "this example" in text and "Unsubscribe" in text and "READ IN APP" in text
    assert "[My Post](https://natesnewsletter.substack.com/p/my-post)" in text
    assert "[the PR](https://github.com/org/repo/pull/7?tab=files)" in text
    assert "![chart](https://substack-post-media.s3.amazonaws.com/public/images/chart.png)" in text


def test_strip_tracking_on_plain_text() -> None:
    text = (f"My Post ( {TITLE_LINK} )\n\nRead more ( {REDIRECT} ).\n"
            f"Unsubscribe {UNSUB}, or see {EXTERNAL}.")
    out = ns._strip_tracking(text)
    for secret in SECRETS:
        assert secret not in out
    assert "My Post ( https://natesnewsletter.substack.com/p/my-post )" in out
    assert "Read more ." in out
    assert "https://github.com/org/repo/pull/7?tab=files." in out


def test_strip_tracking_keeps_code_parentheses() -> None:
    assert ns._strip_tracking("call run() then [x](https://example.com/a)") == \
        "call run() then [x](https://example.com/a)"


# --- sensor fixtures ---------------------------------------------------------

def write_config(tmp_path: Path, **filtering) -> Path:
    cfg = yaml.safe_load((SENSOR_DIR / "config.yaml").read_text())
    cfg["filtering"].update(filtering)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAIL_NEWSLETTERS_USERNAME", "sensor@example.com")
    monkeypatch.setenv("GMAIL_NEWSLETTERS_APP_PASSWORD", "app-password")


@pytest.fixture
def sensor(env, tmp_path: Path):
    s = ns.NewslettersKOISensor(write_config(tmp_path, max_fetch_attempts=3))
    s.state = PersistentSensorState("newsletters-test", tmp_path)
    s.emitted = []
    s.emit_ok = True

    def emit(bundle):
        if not s.emit_ok:
            return False
        s.emitted.append(bundle)
        return True

    s._emit_blocking = emit
    return s


class FakeIMAP:
    def __init__(self, messages: dict[int, bytes]):
        self.messages = messages
        self.fail_fetch: set[int] = set()
        self.fetched: list[int] = []

    def uid(self, command: str, *args):
        if command == "SEARCH":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.messages))]
        if command == "FETCH":
            uid = int(args[0])
            self.fetched.append(uid)
            if uid in self.fail_fetch:
                return "NO", [None]
            raw = self.messages[uid]
            return "OK", [(f"{uid} (RFC822.SIZE {len(raw)} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
        raise AssertionError(command)


def watermark(sensor) -> int:
    return sensor._get_max_uid("KOI/Substack", 7)


def poll(sensor, conn) -> None:
    sensor._poll_folder(conn, "KOI/Substack", 7)


def emitted_docs(sensor) -> list[dict]:
    docs = []
    for b in sensor.emitted:
        contents = b.contents if hasattr(b, "contents") else b["contents"]
        docs.append(contents.get("document", contents) if isinstance(contents, dict) else contents)
    return docs


# --- config ------------------------------------------------------------------

def test_username_comes_from_the_env(sensor) -> None:
    assert sensor.imap_cfg["username"] == "sensor@example.com"


def test_missing_username_env_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GMAIL_NEWSLETTERS_USERNAME", raising=False)
    monkeypatch.setenv("GMAIL_NEWSLETTERS_APP_PASSWORD", "app-password")
    with pytest.raises(RuntimeError, match="GMAIL_NEWSLETTERS_USERNAME"):
        ns.NewslettersKOISensor(write_config(tmp_path))


def test_committed_config_has_no_mailbox_address() -> None:
    import re
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", (SENSOR_DIR / "config.yaml").read_text())


# --- polling and watermark ---------------------------------------------------

def test_emitted_document_has_post_url_and_no_tracking(sensor) -> None:
    conn = FakeIMAP({1: raw_email(1)})
    poll(sensor, conn)
    assert watermark(sensor) == 1
    [bundle] = sensor.emitted
    dumped = bundle.model_dump_json() if hasattr(bundle, "model_dump_json") else str(bundle)
    assert "https://natesnewsletter.substack.com/p/my-post" in dumped
    for secret in SECRETS:
        assert secret not in dumped
    assert "eotrx" not in dumped


def test_fetch_failure_holds_the_watermark_and_retries(sensor) -> None:
    conn = FakeIMAP({1: raw_email(1), 2: raw_email(2), 3: raw_email(3)})
    conn.fail_fetch = {2}
    poll(sensor, conn)
    assert watermark(sensor) == 1
    assert conn.fetched == [1, 2]            # stopped at the failure, 3 not fetched
    assert len(sensor.emitted) == 1

    conn.fail_fetch = set()
    conn.fetched = []
    poll(sensor, conn)
    assert watermark(sensor) == 3
    assert conn.fetched == [2, 3]
    assert len(sensor.emitted) == 3
    assert not sensor.state.metadata.get("folder:KOI/Substack:uidvalidity:7:failed_attempts")


def test_emit_failure_holds_the_watermark_and_retries(sensor) -> None:
    conn = FakeIMAP({1: raw_email(1), 2: raw_email(2)})
    sensor.emit_ok = False
    poll(sensor, conn)
    assert watermark(sensor) == 0
    sensor.emit_ok = True
    poll(sensor, conn)
    assert watermark(sensor) == 2
    assert len(sensor.emitted) == 2


def test_success_after_a_failure_does_not_skip_it(sensor) -> None:
    # The old loop moved the watermark past UID 2 when UID 3 succeeded.
    conn = FakeIMAP({2: raw_email(2), 3: raw_email(3)})
    conn.fail_fetch = {2}
    poll(sensor, conn)
    assert watermark(sensor) == 0
    assert conn.fetched == [2]


def test_a_uid_that_keeps_failing_is_given_up(sensor) -> None:
    conn = FakeIMAP({1: raw_email(1), 2: raw_email(2), 3: raw_email(3)})
    conn.fail_fetch = {2}
    for _ in range(2):
        poll(sensor, conn)
        assert watermark(sensor) == 1
    poll(sensor, conn)                      # third attempt reaches max_fetch_attempts=3
    assert watermark(sensor) == 3
    assert len(sensor.emitted) == 2         # 1 and 3


def test_failure_count_survives_a_restart(sensor, tmp_path: Path) -> None:
    conn = FakeIMAP({1: raw_email(1), 2: raw_email(2)})
    conn.fail_fetch = {2}
    poll(sensor, conn)
    sensor.state.save()
    reloaded = PersistentSensorState("newsletters-test", tmp_path)
    assert reloaded.metadata["folder:KOI/Substack:uidvalidity:7:failed_attempts"] == {"2": 1}


def test_account_mail_is_skipped_and_the_watermark_advances(sensor) -> None:
    conn = FakeIMAP({
        1: raw_email(1, subject="Your payment receipt from Nate’s Substack #ABC-123"),
        2: raw_email(2, subject="Want to make someone's day? (3 free gifts inside)"),
        3: raw_email(3, subject="Welcome to Nate's Newsletter"),
        4: raw_email(4, subject="Correction: Download Links for My Apps from Today’s Post"),
        5: raw_email(5, subject="Thanks for subscribing to Nate’s Newsletter"),
        6: raw_email(6, subject="Here’s $100 to give a friend"),
        7: raw_email(7, subject="💬 New thread from Nate"),
    })
    poll(sensor, conn)
    assert watermark(sensor) == 7
    assert len(sensor.emitted) == 2          # the correction notice and the thread


def test_unrouted_mail_is_skipped(sensor) -> None:
    conn = FakeIMAP({1: raw_email(1, sender="news@example.com")})
    poll(sensor, conn)
    assert watermark(sensor) == 1
    assert sensor.emitted == []


# --- reprocessing -------------------------------------------------------------

def test_force_re_emits_with_the_same_rid_and_dry_run_does_not_emit(sensor) -> None:
    raw = raw_email(1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    assert sensor._process_message("f", 1, raw, cutoff) == ("emitted", "new")
    assert sensor._process_message("f", 1, raw, cutoff) == ("already", "emitted before")
    assert sensor._process_message("f", 1, raw, cutoff, force=True, dry_run=True) == ("emitted", "dry run")
    assert len(sensor.emitted) == 1
    assert sensor._process_message("f", 1, raw, cutoff, force=True) == ("emitted", "new")
    assert len(sensor.emitted) == 2
    rids = {str(b.rid) if hasattr(b, "rid") else b["rid"] for b in sensor.emitted}
    assert len(rids) == 1
