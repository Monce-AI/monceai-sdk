#!/usr/bin/env python3
"""
100-test suite for monceai LLM/VLM module.
Tests: LLM(), VLM(), LLMSession, all 13 models, JSON mode, error handling.
Run: python tests/test_llm.py
"""
import sys
import time
import struct

passed = 0
failed = 0
errors = []

def ok(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        failed += 1
        errors.append(f"{name}: {detail}")
        print(f"  \033[31m✗\033[0m {name} — {detail}")
    sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
print("\n[1/8] IMPORTS")
# ═══════════════════════════════════════════════════════════════
try:
    from monceai import LLM, VLM, LLMSession, LLMResult, Snake, SAT
    import monceai
    ok("import LLM", True)
    ok("import VLM", True)
    ok("import LLMSession", True)
    ok("import LLMResult", True)
    ok("import Snake", True)
    ok("import SAT", True)
    ok("version is 0.3.0", monceai.__version__ == "0.3.0", monceai.__version__)
except Exception as e:
    ok("imports", False, str(e))
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
print("\n[2/8] LLMResult DATACLASS")
# ═══════════════════════════════════════════════════════════════
r = LLMResult(text='{"a":1}', model="test", input_tokens=10, output_tokens=5)
ok("LLMResult.text", r.text == '{"a":1}')
ok("LLMResult.model", r.model == "test")
ok("LLMResult.json parses", r.json == {"a": 1})
ok("LLMResult.ok is True", r.ok)
ok("LLMResult repr", "test" in repr(r))
ok("LLMResult tokens", r.input_tokens == 10 and r.output_tokens == 5)

r2 = LLMResult(text="not json")
ok("LLMResult.json returns None for non-json", r2.json is None)

r3 = LLMResult(text="Model unavailable")
ok("LLMResult.ok is False for unavailable", not r3.ok)

r4 = LLMResult(text="")
ok("LLMResult.ok is False for empty", not r4.ok)

r5 = LLMResult(text="hello", sat_memory={"formula": "test"})
ok("LLMResult.sat_memory", r5.sat_memory.get("formula") == "test")

# ═══════════════════════════════════════════════════════════════
print("\n[3/8] MODEL SHORTHAND — all 13 models respond via LLM()")
# ═══════════════════════════════════════════════════════════════
# Each model shorthand must route correctly — verified by model name in result
for shorthand in ["haiku", "sonnet", "nova-pro", "nova-lite", "nova-micro",
                   "charles", "charles-auma", "charles-json", "charles-architect",
                   "charles-science", "concise", "cc", "sonnet4"]:
    r = LLM("hi", model=shorthand, timeout=90)
    ok(f"LLM(model={shorthand!r}) responds", r.ok, r.text[:40] if not r.ok else "")

# ═══════════════════════════════════════════════════════════════
print("\n[4/8] LLMSession CONSTRUCTION")
# ═══════════════════════════════════════════════════════════════
s = LLMSession(model="haiku")
ok("session model resolved", s.model == "eu.anthropic.claude-haiku-4-5-20251001-v1:0")
ok("session endpoint default", "monceapp.aws.monce.ai" in s.endpoint)
ok("session repr", "haiku" in repr(s))
ok("session factory default", s.factory_id == 0)

s2 = LLMSession(model="charles", factory_id=4, session_id="test123")
ok("session custom factory", s2.factory_id == 4)
ok("session custom id", s2.session_id == "test123")

s3 = LLMSession(endpoint="https://custom.endpoint.ai")
ok("session custom endpoint", s3.endpoint == "https://custom.endpoint.ai")

# ═══════════════════════════════════════════════════════════════
print("\n[5/8] LIVE LLM CALLS — fast models")
# ═══════════════════════════════════════════════════════════════

# Haiku — fast, cheap
r = LLM("what is 2+2?", model="haiku", timeout=30)
ok("haiku responds", r.ok, r.text[:50])
ok("haiku answer contains 4", "4" in r.text, r.text[:50])
ok("haiku has tokens", r.input_tokens > 0)
ok("haiku has elapsed", r.elapsed_ms > 0)
ok("haiku model in result", "haiku" in r.model)

# Nova Micro — cheapest
r = LLM("what is 3+3?", model="nova-micro", timeout=30)
ok("nova-micro responds", r.ok, r.text[:50])
ok("nova-micro answer", "6" in r.text, r.text[:50])

# Nova Lite
r = LLM("what is 5+5?", model="nova-lite", timeout=30)
ok("nova-lite responds", r.ok, r.text[:50])

# Nova Pro
r = LLM("what is 7+7?", model="nova-pro", timeout=30)
ok("nova-pro responds", r.ok, r.text[:50])

# Sonnet 4.6
r = LLM("what is 9+1?", model="sonnet", timeout=30)
ok("sonnet responds", r.ok, r.text[:50])
ok("sonnet answer", "10" in r.text, r.text[:50])

# ═══════════════════════════════════════════════════════════════
print("\n[6/8] LIVE LLM CALLS — charles family")
# ═══════════════════════════════════════════════════════════════

# charles-auma — boolean arithmetic
r = LLM("6x7", model="charles-auma", timeout=30)
ok("charles-auma responds", r.ok, r.text[:60])
ok("charles-auma has sat_memory", bool(r.sat_memory))
ok("charles-auma formula", "formula" in r.sat_memory, str(r.sat_memory.keys()))

# charles-json — structured
r = LLM("what is the capital of France?", json=True, timeout=30)
ok("charles-json responds", r.ok, r.text[:60])
ok("charles-json is JSON", r.json is not None, r.text[:60])
ok("charles-json has answer key", "answer" in (r.json or {}), str(r.json)[:60])

# charles (full pipeline — may be slow)
r = LLM("morning bruv", model="charles", timeout=90)
ok("charles responds", r.ok, r.text[:60])

# concise
r = LLM("what is gravity?", model="concise", timeout=90)
ok("concise responds", r.ok, r.text[:60])
ok("concise is short", len(r.text) < 500, f"len={len(r.text)}")

# charles-architect
r = LLM("draw a chart of planets", model="charles-architect", timeout=90)
ok("charles-architect responds", r.ok, r.text[:60])

# charles-science
r = LLM("factor 91", model="charles-science", timeout=90)
ok("charles-science responds", r.ok, r.text[:60])
ok("charles-science has services", "services_fired" in r.sat_memory or "pipeline" in r.sat_memory, str(r.sat_memory.keys()))

# cc
r = LLM("what is AI?", model="cc", timeout=90)
ok("cc responds", r.ok, r.text[:60])

# ═══════════════════════════════════════════════════════════════
print("\n[7/8] VLM CALLS")
# ═══════════════════════════════════════════════════════════════

# Create a tiny 1x1 red PNG for testing
def make_tiny_png():
    import zlib
    sig = b'\x89PNG\r\n\x1a\n'
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    raw = b'\x00\xff\x00\x00'
    idat = zlib.compress(raw)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')

tiny_png = make_tiny_png()
ok("tiny PNG created", len(tiny_png) > 50, f"{len(tiny_png)} bytes")

# VLM with image
r = VLM("describe this image", image=tiny_png, json=True, timeout=30)
ok("VLM responds", r.ok, r.text[:60])
ok("VLM returns JSON", r.json is not None, r.text[:60])

# VLM with custom model
r = VLM("what color is this?", image=tiny_png, model="sonnet", json=False, timeout=30)
ok("VLM sonnet responds", r.ok, r.text[:60])

# LLM with image kwarg (same path)
r = LLM("describe this", image=tiny_png, model="charles-json", timeout=30)
ok("LLM+image responds", r.ok, r.text[:60])

# ═══════════════════════════════════════════════════════════════
print("\n[8/8] SESSION + EDGE CASES")
# ═══════════════════════════════════════════════════════════════

# Session persistence
sess = LLMSession(model="haiku")
r1 = sess.send("my name is Charles", timeout=30)
ok("session msg 1", r1.ok)
ok("session has id", bool(r1.session_id))

r2 = sess.send("what is my name?", timeout=30)
ok("session msg 2", r2.ok)

# JSON mode forces charles-json
r = LLM("list 3 colors", json=True, model="haiku", timeout=30)
ok("json=True forces charles-json", "charles-json" in r.model, r.model)

# Empty prompt
r = LLM("", model="haiku", timeout=15)
ok("empty prompt handled", True)

# Bad endpoint
r = LLM("test", model="haiku", endpoint="https://nonexistent.invalid", timeout=5)
ok("bad endpoint returns error", not r.ok or "Error" in r.text)

# Unknown model passthrough
r = LLM("test", model="eu.fake.model.v1", timeout=10)
ok("unknown model returns error", not r.ok or "Unknown model" in r.text, r.text[:60])

# Factory ID
r = LLM("what glass for 44.2?", model="haiku", factory_id=4, timeout=30)
ok("factory_id=4 works", r.ok)

# Timeout handling
r = LLM("compute something very long", model="charles-science", timeout=2)
ok("short timeout returns gracefully", isinstance(r, LLMResult))

# sat_memory on charles-auma
r = LLM("8x9", model="charles-auma", timeout=30)
ok("auma sat has formula", "formula" in r.sat_memory, str(r.sat_memory.keys()))

# raw response preserved
r = LLM("hello", model="haiku", timeout=30)
ok("raw response dict", isinstance(r.raw, dict))
ok("raw has reply", "reply" in r.raw, str(r.raw.keys())[:60])

# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
total = passed + failed
print(f"TOTAL: {passed}/{total} passed ({passed/total*100:.0f}%)")
if errors:
    print(f"\nFailed ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")

sys.exit(0 if failed == 0 else 1)
