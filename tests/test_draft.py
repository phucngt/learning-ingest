import json
import sys
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest

from conftest import FIXTURES, read_json
from learning_ingest import __version__, llm
from learning_ingest.cli import main
from learning_ingest.review import run_prepare_review
from learning_ingest.util import sha256_bytes


API_KEY = "test-key-123"
REASONING = ("Suy luận ẩn", "Kiểm tra căn cứ")
FPT_SETTINGS = ("API_KEY", "BASE_URL", "MODEL", "CA_BUNDLE", "MAX_TOKENS",
                "TEMPERATURE", "REASONING_EFFORT", "JSON_MODE", "TIMEOUT")


@pytest.fixture
def invoke(tmp_path, monkeypatch):
    for setting in FPT_SETTINGS:
        monkeypatch.delenv(f"FPT_{setting}", raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(llm, "RETRY_BACKOFF_SECONDS", (0, 0))

    def draft(out, *args):
        return main(["draft", "--out", str(out), "--env-file", str(tmp_path / "chua-co.env"), *args])

    return draft


@pytest.fixture
def api(invoke, monkeypatch):
    requests = []
    responses = deque()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, self.headers, json.loads(body)))
            reply = responses.popleft() if responses else (400, "Hết phản hồi giả lập")
            status, payload, *options = reply
            if status is None:
                return
            if isinstance(payload, bytes):
                data = payload
                content_type = "text/event-stream; charset=utf-8"
            else:
                if not isinstance(payload, str):
                    payload = json.dumps(payload, ensure_ascii=False)
                data = payload.encode("utf-8")
                content_type = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if options == ["abrupt"]:
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                if data:
                    self.wfile.write(f"{len(data):x}\r\n".encode("ascii") + data + b"\r\n")
                return
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        base_url = f"http://127.0.0.1:{server.server_port}/v1"
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        monkeypatch.setenv("FPT_API_KEY", API_KEY)
        monkeypatch.setenv("FPT_BASE_URL", base_url)
        try:
            yield base_url, requests, responses
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture
def valid_reply(prepared):
    reply = read_json(FIXTURES / "ai-output-valid.json")
    reply["package_id"] = read_json(prepared / "review" / "review-manifest.json")["package_id"]
    return reply


def sse(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def completion(content, *, finish_reason="stop", usage=None, done=True):
    if isinstance(content, dict):
        content = json.dumps(content, ensure_ascii=False)
    chunks = [
        b": keep-alive\n\nevent: completion\n",
        sse({"choices": [{"delta": {"role": "assistant"}}]}),
    ]
    chunks.extend(sse({"choices": [{"delta": {"reasoning_content": part}}]}) for part in REASONING)
    midpoint = len(content) // 2
    chunks.extend(sse({"choices": [{"delta": {"content": part}}]})
                  for part in (content[:midpoint], content[midpoint:]))
    chunks.append(sse({"choices": [{"delta": {}, "finish_reason": finish_reason}]}))
    if usage is not None:
        chunks.append(sse({"choices": [], "usage": usage}))
    if done:
        chunks.append(b"data: [DONE]\n\n")
    return 200, b"".join(chunks)


def json_completion(content, *, finish_reason="stop", **fields):
    return 200, {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}], **fields}


def assert_key_hidden(out, captured):
    assert API_KEY not in captured.out + captured.err
    for path in (out / "draft").rglob("*"):
        if path.is_file():
            assert API_KEY.encode() not in path.read_bytes()


def test_draft_then_validate_export(invoke, api, prepared, valid_reply, capsys):
    base_url, requests, responses = api
    usage = {"prompt_tokens": 123, "completion_tokens": 456,
             "completion_tokens_details": {"reasoning_tokens": 234}}
    responses.append(completion(valid_reply, usage=usage))
    input_path = prepared / "review" / "package.md"
    input_bytes = input_path.read_bytes().replace(b"\n", b"\r\n")
    input_path.write_bytes(input_bytes)
    assert invoke(prepared) == 0

    (path, headers, body), = requests
    assert path == "/v1/chat/completions"
    assert headers["Authorization"] == f"Bearer {API_KEY}"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/event-stream"
    assert body["model"] == "GLM-5.3-Flash"
    assert body["temperature"] == 0.2
    assert body["reasoning_effort"] == "low"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert "max_tokens" not in body
    assert "response_format" not in body
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert "JSON" in body["messages"][0]["content"]
    assert body["messages"][1]["content"] == input_bytes.decode("utf-8")

    draft_dir = prepared / "draft"
    out_file = draft_dir / "ai-output.json"
    assert read_json(out_file) == valid_reply
    assert (draft_dir / "response-part-01.txt").read_text(encoding="utf-8") == json.dumps(valid_reply, ensure_ascii=False)
    manifest = read_json(prepared / "review" / "review-manifest.json")
    run = read_json(draft_dir / "draft-run.json")
    assert run["tool"] == "learning-ingest"
    assert run["version"] == __version__
    assert run["provider"] == "fpt"
    assert run["model"] == body["model"]
    assert run["endpoint"] == f"{base_url}/chat/completions"
    assert run["package_id"] == manifest["package_id"]
    assert run["prompt_version"] == manifest["prompt_version"]
    assert datetime.fromisoformat(run["generated_at"]).utcoffset() == timezone.utc.utcoffset(None)
    assert run["temperature"] == 0.2
    assert run["reasoning_effort"] == "low"
    assert run["json_mode"] is False
    entry, = run["parts"]
    assert entry["part"] == 1
    assert entry["input_file"] == input_path.name
    assert entry["input_sha256"] == sha256_bytes(input_bytes)
    assert entry["input_chars"] == len(input_bytes.decode("utf-8"))
    assert entry["output_file"] == out_file.name
    assert entry["finish_reason"] == "stop"
    assert entry["usage"] == usage
    assert entry["reasoning_chars"] == sum(map(len, REASONING))
    assert entry["duration_seconds"] >= 0
    assert entry["status"] == "saved"
    captured = capsys.readouterr()
    assert "learning-ingest validate-export --input" in captured.out
    assert str(out_file) in captured.out
    saved = captured.out + captured.err + (draft_dir / "draft-run.json").read_text(encoding="utf-8")
    assert all(part not in saved for part in REASONING)
    assert_key_hidden(prepared, captured)
    assert main(["validate-export", "--input", str(out_file), "--out", str(prepared)]) == 0


@pytest.mark.parametrize("shape", ["fence", "text-parts", "prose"])
def test_draft_parses_wrapped_reply(invoke, api, prepared, valid_reply, shape):
    _, _, responses = api
    reply = json.dumps(valid_reply, ensure_ascii=False)
    content = {
        "fence": f"\n```json\n{reply}\n```\n",
        "text-parts": [{"type": "text", "text": reply[:100]}, {"type": "text", "text": reply[100:]}],
        "prose": f"Kết quả\n{reply}\nHết.",
    }[shape]
    if shape == "text-parts":
        responses.append(json_completion(content, reasoning_chars=API_KEY))
    else:
        responses.append(completion(content))
    assert invoke(prepared) == 0
    assert read_json(prepared / "draft" / "ai-output.json") == valid_reply
    entry, = read_json(prepared / "draft" / "draft-run.json")["parts"]
    assert ("reasoning_chars" in entry) == (shape != "text-parts")


@pytest.mark.parametrize(("content", "reason", "message"), [
    ("Dở dang {", "stop", "AI không trả về JSON hợp lệ"),
    ('[{"mục": 1}]', "stop", "AI không trả về JSON hợp lệ"),
    ('{"mục": 1e999}', "stop", "AI không trả về JSON hợp lệ"),
    ('{"mục": 1}', "length", "FPT_MAX_TOKENS"),
])
def test_draft_keeps_unusable_reply(invoke, api, prepared, capsys, content, reason, message):
    _, _, responses = api
    responses.append(completion(content, finish_reason=reason))
    assert invoke(prepared) == 1
    output = capsys.readouterr()
    assert message in output.out + output.err
    if reason == "length":
        assert "--max-chars" in output.out + output.err
    assert "response-part-01.txt" in output.out + output.err
    assert (prepared / "draft" / "response-part-01.txt").read_text(encoding="utf-8") == content
    assert not (prepared / "draft" / "ai-output.json").exists()


@pytest.mark.parametrize(("status", "message"), [(401, "API key bị từ chối"), (400, "Chi tiết giả lập")])
def test_draft_remote_error_hides_key(invoke, api, prepared, capsys, status, message):
    _, requests, responses = api
    responses.append((status, f"Chi tiết giả lập: Bearer {API_KEY}"))
    assert invoke(prepared) == 4
    assert len(requests) == 1
    captured = capsys.readouterr()
    assert message in captured.err
    assert_key_hidden(prepared, captured)


def test_draft_does_not_store_echoed_key(invoke, api, prepared, valid_reply, capsys):
    _, _, responses = api
    responses.append(completion({**valid_reply, "echo": API_KEY}, finish_reason=API_KEY, usage={"echo": API_KEY}))
    assert invoke(prepared) == 1
    assert (prepared / "draft" / "response-part-01.txt").is_file()
    assert not (prepared / "draft" / "ai-output.json").exists()
    assert_key_hidden(prepared, capsys.readouterr())


def test_draft_handles_invalid_choice(invoke, api, prepared):
    _, _, responses = api
    responses.append((200, {"choices": [None]}))
    assert invoke(prepared) == 1
    assert (prepared / "draft" / "response-part-01.txt").is_file()


@pytest.mark.parametrize("first_status", [503, 524, None])
def test_draft_retries_temporary_failure(invoke, api, prepared, valid_reply, first_status):
    _, requests, responses = api
    responses.extend([(first_status, "Đang bận"), completion(valid_reply)])
    assert invoke(prepared) == 0
    assert len(requests) == 2
    assert requests[0][2] == requests[1][2]


@pytest.mark.parametrize("bad_data", [b"{", b"\xff"])
def test_draft_rejects_malformed_stream(invoke, api, prepared, capsys, bad_data):
    _, requests, responses = api
    responses.append((200, b"data: " + bad_data + b" " + API_KEY.encode("utf-8") + b"\n\n"))
    assert invoke(prepared) == 4
    assert len(requests) == 1
    captured = capsys.readouterr()
    assert "luồng phản hồi không hợp lệ" in captured.err
    assert_key_hidden(prepared, captured)
    assert not (prepared / "draft" / "response-part-01.txt").exists()
    entry, = read_json(prepared / "draft" / "draft-run.json")["parts"]
    assert entry["status"] == "remote_error"


@pytest.mark.parametrize(("finish_reason", "done"), [("stop", False), (None, True)])
def test_draft_accepts_either_stream_end_marker(invoke, api, prepared, valid_reply, finish_reason, done):
    _, _, responses = api
    responses.append(completion(valid_reply, finish_reason=finish_reason, done=done))
    assert invoke(prepared) == 0
    assert read_json(prepared / "draft" / "ai-output.json") == valid_reply


@pytest.mark.parametrize("valid_json", [True, False])
def test_draft_keeps_raw_when_stream_has_no_end_marker(invoke, api, prepared, valid_reply, capsys, valid_json):
    _, requests, responses = api
    content = json.dumps(valid_reply, ensure_ascii=False) if valid_json else '{"mục":'
    responses.append(completion(content, finish_reason=None, done=False))
    assert invoke(prepared) == 1
    assert len(requests) == 1
    captured = capsys.readouterr()
    for expected in ("giữa chừng sau", "300 giây", "FPT_REASONING_EFFORT=low", "prepare-review --max-chars"):
        assert expected in captured.err
    draft_dir = prepared / "draft"
    assert (draft_dir / "response-part-01.txt").read_text(encoding="utf-8") == content
    assert not (draft_dir / "ai-output.json").exists()
    entry, = read_json(draft_dir / "draft-run.json")["parts"]
    assert entry["status"] == "stream_cut"
    assert type(entry["elapsed_seconds"]) is float
    assert entry["elapsed_seconds"] >= 0
    assert entry["finish_reason"] is None
    assert entry["output_file"] is None


@pytest.mark.parametrize("data", [b"", sse({"choices": [{"delta": {"content": "Dở dang"}}]})])
def test_draft_does_not_retry_abrupt_stream_disconnect(invoke, api, prepared, capsys, data):
    _, requests, responses = api
    responses.append((200, data, "abrupt"))
    assert invoke(prepared) == 4
    assert len(requests) == 1
    assert "Luồng phản hồi bị ngắt giữa chừng sau" in capsys.readouterr().err
    draft_dir = prepared / "draft"
    entry, = read_json(draft_dir / "draft-run.json")["parts"]
    assert entry["status"] == "remote_error"
    assert not (draft_dir / "ai-output.json").exists()


def test_stream_completion_progress_and_final_metadata(monkeypatch, capsys):
    times = iter([0, 29, 30, 59, 60])
    monkeypatch.setattr(llm, "time", SimpleNamespace(monotonic=lambda: next(times)))
    result = llm._stream_completion([
        sse({"choices": [{"delta": {"reasoning_content": API_KEY}, "finish_reason": "old"}],
             "usage": {"total_tokens": 1}}),
        sse({"choices": [{"delta": {"content": "Đáp"}, "finish_reason": "stop"}]}),
        sse({"choices": [{"delta": {"content": " án"}, "finish_reason": None}]}),
        sse({"choices": [], "usage": {"total_tokens": 2}}),
        b"data: [DONE]\n\n",
        b"data: ignored after end\n\n",
    ])
    assert result == {
        "choices": [{"message": {"content": "Đáp án"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 2},
        "reasoning_chars": len(API_KEY),
    }
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.splitlines() == [
        f"Đang nhận phản hồi (30 giây, {len(API_KEY)} ký tự suy luận, 3 ký tự nội dung).",
        f"Đang nhận phản hồi (60 giây, {len(API_KEY)} ký tự suy luận, 6 ký tự nội dung).",
    ]


def test_draft_config_errors_and_default_url(invoke, prepared, monkeypatch, capsys):
    assert invoke(prepared) == 2
    assert "FPT_API_KEY" in capsys.readouterr().err
    monkeypatch.setenv("FPT_API_KEY", API_KEY)
    monkeypatch.setenv("FPT_BASE_URL", "http://example.com/v1")
    assert invoke(prepared) == 2
    assert "FPT_BASE_URL" in capsys.readouterr().err
    monkeypatch.delenv("FPT_BASE_URL")
    assert invoke(prepared, "--dry-run") == 0
    assert "https://token-api.fpt.ai/v1/chat/completions" in capsys.readouterr().out
    assert not (prepared / "draft").exists()


@pytest.mark.parametrize(("setting", "effort"), [("high", "high"), ("max", "max"), ("none", None), ("", None)])
def test_draft_reasoning_effort_override(invoke, api, prepared, valid_reply, monkeypatch, setting, effort):
    _, requests, responses = api
    monkeypatch.setenv("FPT_REASONING_EFFORT", setting)
    responses.append(completion(valid_reply))
    assert invoke(prepared) == 0
    (_, _, body), = requests
    if effort is None:
        assert "reasoning_effort" not in body
    else:
        assert body["reasoning_effort"] == effort
    assert read_json(prepared / "draft" / "draft-run.json")["reasoning_effort"] == effort


@pytest.mark.parametrize("setting", ["medium", "LOW", " low", "low "])
def test_draft_invalid_reasoning_effort_fails_before_request(invoke, api, prepared, monkeypatch, capsys, setting):
    _, requests, _ = api
    monkeypatch.setenv("FPT_REASONING_EFFORT", setting)
    assert invoke(prepared) == 2
    assert requests == []
    assert not (prepared / "draft").exists()
    message = capsys.readouterr().err
    for expected in ("FPT_REASONING_EFFORT", "low", "high", "max", "none", "rỗng"):
        assert expected in message


def test_draft_tls_loads_custom_bundle(invoke, tmp_path, monkeypatch):
    bundle = tmp_path / "test-ca.pem"
    monkeypatch.setenv("FPT_API_KEY", API_KEY)
    monkeypatch.setenv("FPT_CA_BUNDLE", str(bundle))
    context = object()
    calls = []

    def create_context(*, cafile):
        calls.append(cafile)
        return context

    monkeypatch.setattr(llm.ssl, "create_default_context", create_context)
    config = llm.load_config(env_file=tmp_path / "chua-co.env")
    assert llm._ssl_context(config.ca_bundle) is context
    assert [str(path) for path in calls] == [str(bundle)]


@pytest.mark.parametrize("cafile", ["certifi-ca.pem", None])
def test_draft_tls_uses_certifi_when_available(monkeypatch, cafile):
    certifi = SimpleNamespace(where=lambda: cafile) if cafile else None
    monkeypatch.setitem(sys.modules, "certifi", certifi)
    calls = []

    def create_context(**kwargs):
        calls.append(kwargs.get("cafile"))

    monkeypatch.setattr(llm.ssl, "create_default_context", create_context)
    llm._ssl_context(None)
    assert calls == [cafile]


def test_draft_tls_verification_failure(invoke, prepared, monkeypatch, capsys):
    monkeypatch.setenv("FPT_API_KEY", API_KEY)
    calls = []

    class FakeOpener:
        def open(self, request, *, timeout):
            calls.append(timeout)
            raise llm.urllib.error.URLError(llm.ssl.SSLCertVerificationError("Chứng chỉ hết hạn"))

    monkeypatch.setattr(llm.urllib.request, "build_opener", lambda *_handlers: FakeOpener())
    assert invoke(prepared) == 4
    assert calls == [600]
    captured = capsys.readouterr()
    assert "FPT_CA_BUNDLE" in captured.err
    assert_key_hidden(prepared, captured)


def test_draft_timeout_override(invoke, api, prepared, valid_reply, monkeypatch):
    _, _, responses = api
    responses.append(completion(valid_reply))
    monkeypatch.setenv("FPT_TIMEOUT", "30")
    build_opener = llm.urllib.request.build_opener
    timeouts = []

    def recording_opener(*handlers):
        opener = build_opener(*handlers)
        open_request = opener.open

        def record_timeout(request, *, timeout):
            timeouts.append(timeout)
            return open_request(request, timeout=timeout)

        opener.open = record_timeout
        return opener

    monkeypatch.setattr(llm.urllib.request, "build_opener", recording_opener)
    assert invoke(prepared, "--timeout", "1.5") == 0
    assert timeouts == [1.5]


def test_draft_existing_output_requires_force(invoke, api, prepared, valid_reply):
    _, requests, responses = api
    out_file = prepared / "draft" / "ai-output.json"
    out_file.parent.mkdir()
    out_file.write_text("{}", encoding="utf-8")
    assert invoke(prepared) == 2
    assert requests == []
    assert read_json(out_file) == {}
    responses.append(completion(valid_reply))
    assert invoke(prepared, "--force") == 0
    assert len(requests) == 1
    assert read_json(out_file) == valid_reply


def test_draft_multi_part_order_and_resume(invoke, api, prepared, manifest, valid_reply, capsys):
    _, requests, responses = api
    review = run_prepare_review(manifest, prepared, max_chars=1000, log=lambda _: None)
    count = len(review.parts)
    assert count >= 2
    valid_reply["package_id"] = review.package_id
    draft_dir = prepared / "draft"
    targets = [draft_dir / f"ai-output-part-{k:02d}-of-{count:02d}.json" for k in range(1, count + 1)]

    assert invoke(prepared, "--part", str(count + 1)) == 2
    assert requests == []
    responses.extend([completion(valid_reply)] * count)
    assert invoke(prepared) == 0
    assert [req[2]["messages"][1]["content"] for req in requests] == [
        path.read_text(encoding="utf-8") for path in review.parts
    ]
    assert all(read_json(path) == valid_reply for path in targets)
    next_command = next(line for line in capsys.readouterr().out.splitlines() if "learning-ingest validate-export" in line)
    assert next_command.count("--input") == count
    positions = [next_command.index(str(path)) for path in targets]
    assert positions == sorted(positions)

    requests.clear()
    responses.append(completion(valid_reply))
    assert invoke(prepared, "--part", "2", "--force") == 0
    assert len(requests) == 1
    assert requests[0][2]["messages"][1]["content"] == review.parts[1].read_text(encoding="utf-8")
    run = read_json(draft_dir / "draft-run.json")
    assert [entry["part"] for entry in run["parts"]] == list(range(1, count + 1))


def test_draft_multi_part_preserves_success_after_invalid_reply(invoke, api, prepared, manifest, valid_reply):
    _, requests, responses = api
    review = run_prepare_review(manifest, prepared, max_chars=1000, log=lambda _: None)
    count = len(review.parts)
    valid_reply["package_id"] = review.package_id
    responses.extend([completion("{")] + [completion(valid_reply)] * (count - 1))
    assert invoke(prepared) == 1
    assert len(requests) == count
    assert not (prepared / "draft" / f"ai-output-part-01-of-{count:02d}.json").exists()
    assert read_json(prepared / "draft" / f"ai-output-part-02-of-{count:02d}.json") == valid_reply
    responses.append(completion(valid_reply))
    assert invoke(prepared, "--part", "1") == 0
    run = read_json(prepared / "draft" / "draft-run.json")
    assert [entry["status"] for entry in run["parts"]] == ["saved"] * count


def test_draft_env_file_and_environment_precedence(invoke, api, prepared, valid_reply, tmp_path, monkeypatch):
    base_url, requests, responses = api
    monkeypatch.delenv("FPT_API_KEY")
    monkeypatch.delenv("FPT_BASE_URL")
    env_file = tmp_path / "gia-lap.env"
    env_file.write_text(f"# Cấu hình giả lập\n\nexport FPT_API_KEY = '{API_KEY}' \n"
                        f' FPT_BASE_URL = "{base_url}/"\nFPT_MODEL= tu-tep \n', encoding="utf-8")
    responses.extend([completion(valid_reply), completion(valid_reply)])
    assert invoke(prepared, "--env-file", str(env_file)) == 0
    assert requests[0][1]["Authorization"] == f"Bearer {API_KEY}"
    assert requests[0][2]["model"] == "tu-tep"

    monkeypatch.setenv("FPT_MODEL", "tu-moi-truong")
    monkeypatch.setenv("FPT_MAX_TOKENS", "1234")
    monkeypatch.setenv("FPT_TEMPERATURE", "0.4")
    monkeypatch.setenv("FPT_JSON_MODE", "true")
    assert invoke(prepared, "--env-file", str(env_file), "--force") == 0
    body = requests[1][2]
    assert body["model"] == "tu-moi-truong"
    assert body["max_tokens"] == 1234
    assert body["temperature"] == 0.4
    assert body["response_format"] == {"type": "json_object"}


def test_draft_dry_run(invoke, api, prepared, capsys, monkeypatch):
    base_url, requests, _ = api
    monkeypatch.setenv("FPT_REASONING_EFFORT", "high")
    chars = read_json(prepared / "review" / "review-manifest.json")["parts"][0]["chars"]
    assert invoke(prepared, "--dry-run", "--model", "model-xem-truoc") == 0
    assert requests == []
    assert not (prepared / "draft").exists()
    captured = capsys.readouterr()
    for expected in ("FPT", "model-xem-truoc", f"{base_url}/chat/completions", "reasoning_effort: high", "package.md"):
        assert expected in captured.out
    assert str(chars) in captured.out.replace(",", "")
    assert_key_hidden(prepared, captured)


def test_draft_warns_and_keeps_other_package_id(invoke, api, prepared, valid_reply, capsys):
    _, _, responses = api
    valid_reply["package_id"] = "pkg-khac"
    responses.append(completion(valid_reply))
    assert invoke(prepared) == 0
    assert read_json(prepared / "draft" / "ai-output.json") == valid_reply
    captured = capsys.readouterr()
    assert "package_id" in captured.out + captured.err


def test_draft_requires_review_manifest(invoke, api, tmp_path, capsys):
    assert invoke(tmp_path) == 2
    assert "prepare-review" in capsys.readouterr().err
    assert api[1] == []
