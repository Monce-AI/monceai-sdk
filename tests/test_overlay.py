#!/usr/bin/env python3
"""
Test suite for v1.1.0 overlay classes: Matching, Calc, Diff.

Runs live against https://monceapp.aws.monce.ai. No mocks — these are
end-to-end smoke tests, same style as test_llm.py.

Run: python tests/test_overlay.py
"""
import sys

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
print("\n[1/7] IMPORTS + VERSION")
# ═══════════════════════════════════════════════════════════════
try:
    import monceai
    from monceai import Matching, Calc, Diff
    ok("import Matching", True)
    ok("import Calc", True)
    ok("import Diff", True)
    ok("version >= 1.1.0", monceai.__version__ >= "1.1.0", monceai.__version__)
except Exception as e:
    ok("imports", False, str(e))
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
print("\n[2/7] MRO — str/dict subclasses")
# ═══════════════════════════════════════════════════════════════
ok("Matching is a dict", issubclass(Matching, dict))
ok("Calc is a str", issubclass(Calc, str))
ok("Diff is a dict", issubclass(Diff, dict))


# ═══════════════════════════════════════════════════════════════
print("\n[3/7] VALIDATION (offline)")
# ═══════════════════════════════════════════════════════════════
try:
    Matching("44.2", field="bogus", factory_id=4)
    ok("unknown field raises ValueError", False, "no error")
except ValueError:
    ok("unknown field raises ValueError", True)

try:
    Matching({"x": 1}, field="verre", factory_id=4)
    ok("article mode with dict raises TypeError", False, "no error")
except TypeError:
    ok("article mode with dict raises TypeError", True)

try:
    Calc(42)
    ok("Calc rejects non-string", False, "no error")
except TypeError:
    ok("Calc rejects non-string", True)


# ═══════════════════════════════════════════════════════════════
print("\n[4/7] Calc — exact arithmetic")
# ═══════════════════════════════════════════════════════════════
c = Calc("123x3456")
ok("Calc('123x3456') == '425088'", str(c) == "425088", str(c))
ok("int(Calc)", int(c) == 425088)
ok("float(Calc)", float(c) == 425088.0)
ok("Calc.expression", c.expression == "123x3456")
ok("Calc.result.model == 'calc'", c.result.model == "calc")
ok("Calc.result.elapsed_ms > 0", c.result.elapsed_ms > 0)

c2 = Calc("100/3")
ok("Calc('100/3') starts with 33.333", str(c2).startswith("33.333"), str(c2))

c3 = Calc("1000000x1000000")
ok("Calc('1000000x1000000') huge", str(c3) == "1000000000000", str(c3))


# ═══════════════════════════════════════════════════════════════
print("\n[5/7] Matching — article mode")
# ═══════════════════════════════════════════════════════════════
m = Matching("44.2 rTherm", field="verre", factory_id=4)
ok("num_article returned", m.get("num_article") is not None, str(dict(m))[:80])
ok("denomination returned", m.get("denomination") is not None)
ok("confidence numeric", isinstance(m.get("confidence"), (int, float)))
ok("method present", m.get("method") is not None)
ok("candidates is list", isinstance(m.get("candidates"), list))
ok("result.model == 'matching.article'", m.result.model == "matching.article")
ok("dict unpacking works", bool(dict(**m)))


# ═══════════════════════════════════════════════════════════════
print("\n[6/7] Matching — client mode (text / dict / batch / client)")
# ═══════════════════════════════════════════════════════════════
m = Matching("LGB Menuiserie", factory_id=4)
ok("text mode: numero_client present", m.get("numero_client") is not None, str(dict(m))[:80])
ok("text mode: parsed has nom", (m.get("parsed") or {}).get("nom") is not None)
ok("text mode: method present", m.get("method") is not None)

m2 = Matching({"nom": "LGB", "qty": 50, "adresse": "Lyon"}, factory_id=4)
ok("overlay: qty preserved", m2.get("qty") == 50)
ok("overlay: adresse preserved", m2.get("adresse") == "Lyon")
ok("overlay: numero_client added", m2.get("numero_client") is not None, str(dict(m2))[:80])

batch = Matching(["LGB", "ACTIF PVC"], factory_id=4)
ok("batch returns list", isinstance(batch, list))
ok("batch length", len(batch) == 2)
ok("batch items are Matching", all(isinstance(m, Matching) for m in batch))

client = Matching(factory_id=4)
ok("client mode returns reusable client", "Matching(endpoint=" in repr(client))
fut = client("LGB")
ok("future resolves on get", fut.get("numero_client") is not None)


# ═══════════════════════════════════════════════════════════════
print("\n[7/7] Diff — raw vs enhanced")
# ═══════════════════════════════════════════════════════════════
d = Diff("Quel intercalaire pour 44.2 rTherm?", factory_id=4)
ok("Diff has 'raw' key", "raw" in d)
ok("Diff has 'enhanced' key", "enhanced" in d)
ok("Diff has 'diff' key", "diff" in d)
ok("raw_text is str", isinstance(d.raw_text, str))
ok("enhanced_text is str", isinstance(d.enhanced_text, str))
ok("context_tokens_added > 0", d.context_tokens_added > 0, str(d.context_tokens_added))
ok("report() contains both answers",
   d.raw_text[:20] in d.report() and d.enhanced_text[:20] in d.report())
ok("Diff.result.model starts with diff/", d.result.model.startswith("diff/"))


# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
total = passed + failed
print(f"TOTAL: {passed}/{total} passed ({passed/total*100:.0f}%)")
if errors:
    print(f"\nFailed ({len(errors)}):")
    for e in errors:
        print(f"  - {e}")

sys.exit(0 if failed == 0 else 1)
