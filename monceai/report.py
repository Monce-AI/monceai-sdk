"""
monceai.report — Snake Audit Report Generator.

Produces a comprehensive audit package as a ZIP file.

Two modes:
  1. Global audit (no test data): model introspection, training profile, class balance
  2. Datapoint audit (with test data): ranked predictions, per-item audit traces, metrics

Output:
  snake_audit_<model_id>/
    EXECUTIVE_SUMMARY.html         — print-to-PDF quality report
    MODEL_CARD.json                — version, config, features, classes, profiles
    TRAINING_PROFILE.json          — class distribution, feature stats, data types
    COST_AND_PERFORMANCE.json      — training time, Lambda costs, inference latency
    model.json                     — full Snake model for reproducibility
    ranked_results.csv             — scored + ranked test items (if test data)
    audit_traces/
      SUMMARY.txt                  — aggregated audit overview
      001_<prediction>.txt         — per-datapoint audit trace
      002_<prediction>.txt
      ...
"""

import csv
import io
import json
import os
import zipfile
from datetime import datetime
from time import time


def generate_report(model, test_data=None, target_class=None, top=50,
                    budget_ms=10000, output_path=None):
    """
    Generate a comprehensive audit report.

    Args:
        model: monceai.Snake instance (trained or connected)
        test_data: list[dict] of items to score (optional)
        target_class: class to rank by (required if test_data provided)
        top: number of top items to include detailed audits for
        budget_ms: budget for scoring
        output_path: path for the ZIP file (default: snake_audit_<model_id>.zip)

    Returns:
        str: path to the generated ZIP file
    """
    t0 = time()
    model_id = model.model_id

    if not output_path:
        output_path = f"snake_audit_{model_id}.zip"

    prefix = f"snake_audit_{model_id}"

    # --- Collect data from the API ---
    # Model info
    try:
        model_info = model.info()
    except Exception:
        model_info = {"model_id": model_id, "status": "unknown"}

    # Download full model
    model_path = f"/tmp/_report_model_{model_id}.json"
    model.to_json(model_path)
    with open(model_path) as f:
        model_json = json.load(f)
    os.unlink(model_path)

    # Extract training profile
    population = model_json.get("population", [])
    targets = model_json.get("targets", [])
    header = model_json.get("header", [])
    datatypes = model_json.get("datatypes", [])
    config = model_json.get("config", {})
    n_layers = len(model_json.get("layers", []))

    # Class distribution
    class_counts = {}
    for t in targets:
        k = str(t)
        class_counts[k] = class_counts.get(k, 0) + 1
    classes = sorted(class_counts.keys())
    n_samples = len(population)

    # Feature profile
    features = []
    for i in range(1, len(header)):
        h = header[i]
        dt = datatypes[i] if i < len(datatypes) else "?"
        vals = [row.get(h) for row in population if row.get(h) is not None]
        profile = {"name": h, "type": dt, "n_values": len(vals), "n_unique": len(set(str(v) for v in vals))}
        if dt == "N" and vals:
            nums = [v for v in vals if isinstance(v, (int, float))]
            if nums:
                profile["min"] = min(nums)
                profile["max"] = max(nums)
                profile["mean"] = round(sum(nums) / len(nums), 4)
        elif dt == "T" and vals:
            lengths = [len(str(v)) for v in vals]
            profile["avg_length"] = round(sum(lengths) / len(lengths), 1)
            profile["min_length"] = min(lengths)
            profile["max_length"] = max(lengths)
        features.append(profile)

    # --- Score test data if provided ---
    rank_result = None
    test_predictions = []
    audit_traces = []

    if test_data:
        if not target_class:
            target_class = classes[0] if classes else "unknown"

        # Rank
        rank_result = model.get_batch_rank(
            test_data, target_class=target_class,
            top=top, budget_ms=budget_ms,
        )

        # Get audits for top items
        for i, entry in enumerate(rank_result.top[:top]):
            try:
                audit = model.get_audit(entry["item"])
            except Exception:
                audit = "(audit unavailable)"
            audit_traces.append({
                "rank": i + 1,
                "item": entry["item"],
                "prediction": entry["prediction"],
                "score": entry["score"],
                "probability": entry["probability"],
                "audit": audit,
            })

    report_time = time() - t0

    # --- Build ZIP ---
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # MODEL_CARD.json
        model_card = {
            "model_id": model_id,
            "snake_version": model_json.get("version", "unknown"),
            "target_column": model_json.get("target", header[0] if header else "unknown"),
            "n_samples": n_samples,
            "n_features": len(header) - 1,
            "n_layers": n_layers,
            "n_classes": len(classes),
            "classes": classes,
            "class_distribution": class_counts,
            "config": config,
            "features": [{"name": header[i], "type": datatypes[i] if i < len(datatypes) else "?"} for i in range(1, len(header))],
        }
        zf.writestr(f"{prefix}/MODEL_CARD.json", json.dumps(model_card, indent=2, default=str))

        # TRAINING_PROFILE.json
        training_profile = {
            "n_samples": n_samples,
            "n_features": len(header) - 1,
            "n_classes": len(classes),
            "class_distribution": class_counts,
            "class_balance": {k: round(v / max(n_samples, 1), 4) for k, v in class_counts.items()},
            "features": features,
            "datatypes": {header[i]: datatypes[i] for i in range(len(header)) if i < len(datatypes)},
            "oppose_profile": config.get("oppose_profile", "unknown"),
            "bucket_size": config.get("bucket", 250),
            "noise_ratio": config.get("noise", 0.25),
        }
        zf.writestr(f"{prefix}/TRAINING_PROFILE.json", json.dumps(training_profile, indent=2, default=str))

        # COST_AND_PERFORMANCE.json
        cost_perf = {
            "training": model.training_info or {},
            "report_generation_seconds": round(report_time, 2),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        if rank_result:
            cost_perf["ranking"] = {
                "n_scored": rank_result.n_scored,
                "n_total": rank_result.n_total,
                "n_workers": rank_result.n_workers,
                "wall_clock_ms": rank_result.wall_clock_ms,
                "breakdown": rank_result.breakdown,
            }
        zf.writestr(f"{prefix}/COST_AND_PERFORMANCE.json", json.dumps(cost_perf, indent=2, default=str))

        # model.json
        zf.writestr(f"{prefix}/model.json", json.dumps(model_json, default=str))

        # ranked_results.csv
        if rank_result:
            csv_buf = io.StringIO()
            if rank_result.top:
                fieldnames = ["rank", "score", "prediction"] + sorted(rank_result.top[0]["item"].keys())
                writer = csv.DictWriter(csv_buf, fieldnames=fieldnames)
                writer.writeheader()
                for i, entry in enumerate(rank_result.top):
                    row = {"rank": i + 1, "score": round(entry["score"], 4), "prediction": entry["prediction"]}
                    row.update(entry["item"])
                    writer.writerow(row)
            zf.writestr(f"{prefix}/ranked_results.csv", csv_buf.getvalue())

        # audit_traces/
        if audit_traces:
            # SUMMARY.txt
            summary_lines = [
                f"SNAKE AUDIT TRACE SUMMARY",
                f"Model: {model_id}",
                f"Target class: {target_class}",
                f"Items scored: {rank_result.n_scored if rank_result else 0}",
                f"Top {len(audit_traces)} audited",
                f"Generated: {datetime.utcnow().isoformat()}Z",
                "",
                "=" * 60,
                "",
            ]
            for at in audit_traces:
                summary_lines.append(f"#{at['rank']:3d}  P({target_class})={at['score']:.3f}  -> {at['prediction']}  {_item_summary(at['item'])}")
            zf.writestr(f"{prefix}/audit_traces/SUMMARY.txt", "\n".join(summary_lines))

            # Individual traces
            for at in audit_traces:
                filename = f"{at['rank']:03d}_{at['prediction']}.txt"
                lines = [
                    f"AUDIT TRACE — Rank #{at['rank']}",
                    f"=" * 60,
                    f"",
                    f"Input:",
                    *[f"  {k}: {v}" for k, v in at["item"].items()],
                    f"",
                    f"Prediction: {at['prediction']}",
                    f"P({target_class}): {at['score']:.4f}",
                    f"Full probability:",
                    *[f"  P({cls}): {prob:.4f}" for cls, prob in sorted(at["probability"].items(), key=lambda x: -x[1])],
                    f"",
                    f"{'=' * 60}",
                    f"SNAKE AUDIT TRACE",
                    f"{'=' * 60}",
                    f"",
                    at["audit"],
                ]
                zf.writestr(f"{prefix}/audit_traces/{filename}", "\n".join(lines))
        else:
            # Global mode — audit a few training samples
            zf.writestr(f"{prefix}/audit_traces/SUMMARY.txt",
                         f"GLOBAL AUDIT — No test data provided.\n"
                         f"Model: {model_id}\n"
                         f"Classes: {', '.join(classes)}\n"
                         f"Samples: {n_samples}\n"
                         f"Layers: {n_layers}\n"
                         f"Profile: {config.get('oppose_profile', '?')}\n")

        # EXECUTIVE_SUMMARY.html
        html = _build_executive_summary(
            model_id=model_id,
            model_card=model_card,
            training_profile=training_profile,
            cost_perf=cost_perf,
            rank_result=rank_result,
            audit_traces=audit_traces,
            target_class=target_class,
            classes=classes,
            class_counts=class_counts,
            n_samples=n_samples,
            features=features,
        )
        zf.writestr(f"{prefix}/EXECUTIVE_SUMMARY.html", html)

    # Write ZIP to disk
    with open(output_path, "wb") as f:
        f.write(buf.getvalue())

    return output_path


def _item_summary(item, max_len=60):
    """One-line summary of an item dict."""
    parts = [f"{k}={v}" for k, v in item.items()]
    s = ", ".join(parts)
    return s[:max_len] + "..." if len(s) > max_len else s


def _bar(pct, width=20):
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _build_executive_summary(model_id, model_card, training_profile, cost_perf,
                              rank_result, audit_traces, target_class, classes,
                              class_counts, n_samples, features):
    """Build a print-quality HTML executive summary."""

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    config = model_card.get("config", {})
    n_layers = model_card.get("n_layers", "?")

    # Class distribution table
    class_rows = ""
    for cls in classes:
        count = class_counts.get(cls, 0)
        pct = round(count / max(n_samples, 1) * 100, 1)
        class_rows += f"<tr><td>{cls}</td><td>{count}</td><td>{pct}%</td><td><div class='bar' style='width:{pct}%'></div></td></tr>\n"

    # Feature table
    feature_rows = ""
    for f in features:
        detail = ""
        if f["type"] == "N":
            detail = f"min={f.get('min','?')}, max={f.get('max','?')}, mean={f.get('mean','?')}"
        elif f["type"] == "T":
            detail = f"avg_len={f.get('avg_length','?')}, range=[{f.get('min_length','?')}-{f.get('max_length','?')}]"
        feature_rows += f"<tr><td>{f['name']}</td><td><code>{f['type']}</code></td><td>{f['n_unique']}</td><td>{detail}</td></tr>\n"

    # Ranking results
    ranking_section = ""
    if rank_result and audit_traces:
        result_rows = ""
        for at in audit_traces[:20]:
            prob_bars = " ".join(f"<span class='prob-chip'>{cls}: {at['probability'].get(cls, 0):.0%}</span>" for cls in sorted(at["probability"].keys(), key=lambda c: -at["probability"].get(c, 0))[:3])
            result_rows += f"""<tr>
                <td>#{at['rank']}</td>
                <td><strong>{at['score']:.4f}</strong></td>
                <td>{at['prediction']}</td>
                <td class='mono'>{_item_summary(at['item'], 80)}</td>
                <td>{prob_bars}</td>
            </tr>\n"""

        ranking_section = f"""
        <h2>3. Ranked Results — Top by P({target_class})</h2>
        <div class="stats-grid">
            <div class="stat"><div class="stat-value">{rank_result.n_scored}</div><div class="stat-label">Items Scored</div></div>
            <div class="stat"><div class="stat-value">{rank_result.n_workers}</div><div class="stat-label">Workers</div></div>
            <div class="stat"><div class="stat-value">{rank_result.wall_clock_ms}ms</div><div class="stat-label">Wall Clock</div></div>
            <div class="stat"><div class="stat-value">{len(audit_traces)}</div><div class="stat-label">Audited</div></div>
        </div>
        <table>
            <thead><tr><th>Rank</th><th>P({target_class})</th><th>Prediction</th><th>Item</th><th>Distribution</th></tr></thead>
            <tbody>{result_rows}</tbody>
        </table>
        """

    # Audit detail section
    audit_section = ""
    if audit_traces:
        audit_items = ""
        for at in audit_traces[:5]:
            audit_items += f"""
            <div class="audit-card">
                <div class="audit-header">#{at['rank']} — Predicted: <strong>{at['prediction']}</strong> — P({target_class})={at['score']:.4f}</div>
                <div class="audit-input">
                    {' &nbsp;|&nbsp; '.join(f'<strong>{k}</strong>: {v}' for k, v in at['item'].items())}
                </div>
                <pre class="audit-trace">{at['audit'][:2000]}</pre>
            </div>
            """
        audit_section = f"""
        <h2>4. Audit Traces (Top {min(5, len(audit_traces))})</h2>
        <p>Each trace shows the SAT clause logic: how the model routed the input through its decision tree and which training samples (lookalikes) it matched against. Every decision is explainable.</p>
        {audit_items}
        <p class="note">Full audit traces for all {len(audit_traces)} items are in <code>audit_traces/</code>.</p>
        """

    # Performance section
    training_info = cost_perf.get("training", {})
    breakdown = training_info.get("breakdown", {})

    perf_section = f"""
    <h2>{'5' if audit_traces else '3'}. Cost and Performance</h2>
    <table>
        <thead><tr><th>Metric</th><th>Value</th></tr></thead>
        <tbody>
            <tr><td>Training wall clock (server)</td><td><strong>{training_info.get('wall_clock_ms', '?')}ms</strong></td></tr>
            <tr><td>Preprocessing</td><td>{breakdown.get('preprocess_ms', '?')}ms</td></tr>
            <tr><td>Chain building</td><td>{breakdown.get('chain_build_ms', '?')}ms</td></tr>
            <tr><td>Bucket SAT fan-out</td><td>{breakdown.get('bucket_fan_out_ms', '?')}ms</td></tr>
            <tr><td>Merge + S3</td><td>{breakdown.get('merge_s3_ms', '?')}ms</td></tr>
            <tr><td>Bucket Lambda workers</td><td>{training_info.get('n_bucket_lambdas', '?')}</td></tr>
            <tr><td>Report generation</td><td>{cost_perf.get('report_generation_seconds', '?')}s</td></tr>
        </tbody>
    </table>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Snake Audit Report — {model_id}</title>
<style>
    @page {{ margin: 2cm; }}
    @media print {{
        .no-print {{ display: none; }}
        body {{ font-size: 10pt; }}
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; color: #1a1a1a; line-height: 1.6; max-width: 1100px; margin: 0 auto; padding: 40px; background: #fff; }}
    h1 {{ font-size: 1.8em; margin-bottom: 4px; color: #111; }}
    h2 {{ font-size: 1.3em; margin-top: 36px; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 2px solid #e0e0e0; color: #222; }}
    .subtitle {{ color: #666; margin-bottom: 24px; font-size: 0.95em; }}
    .header-meta {{ display: flex; gap: 24px; margin-bottom: 8px; color: #555; font-size: 0.85em; }}
    .header-meta span {{ background: #f4f4f4; padding: 2px 10px; border-radius: 3px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0 24px; font-size: 0.9em; }}
    th {{ background: #f8f8f8; text-align: left; padding: 8px 12px; border-bottom: 2px solid #ddd; font-weight: 600; color: #444; text-transform: uppercase; font-size: 0.75em; letter-spacing: 0.5px; }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
    tr:hover td {{ background: #fafafa; }}
    .bar {{ height: 14px; background: #2563eb; border-radius: 2px; min-width: 2px; }}
    .mono {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.85em; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }}
    .stat {{ background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 16px; text-align: center; }}
    .stat-value {{ font-size: 1.8em; font-weight: 700; color: #2563eb; }}
    .stat-label {{ font-size: 0.75em; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
    .audit-card {{ background: #f8f9fa; border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px; margin: 12px 0; }}
    .audit-header {{ font-weight: 600; margin-bottom: 6px; color: #333; }}
    .audit-input {{ color: #555; margin-bottom: 10px; font-size: 0.9em; }}
    .audit-trace {{ background: #1a1a2e; color: #a0e0a0; padding: 12px; border-radius: 4px; font-size: 0.8em; line-height: 1.5; max-height: 300px; overflow-y: auto; white-space: pre-wrap; }}
    .prob-chip {{ display: inline-block; background: #e8f0fe; color: #1a73e8; padding: 1px 6px; border-radius: 3px; font-size: 0.8em; margin: 1px; }}
    .note {{ color: #888; font-size: 0.85em; font-style: italic; margin-top: 8px; }}
    .footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid #e0e0e0; color: #999; font-size: 0.8em; text-align: center; }}
    .disclaimer {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 12px; margin: 24px 0; font-size: 0.85em; color: #856404; }}
</style>
</head>
<body>

<h1>Snake Audit Report</h1>
<div class="subtitle">Explainable SAT-based classification — model introspection and decision audit</div>
<div class="header-meta">
    <span>Model: <strong>{model_id}</strong></span>
    <span>Snake v{model_card.get('snake_version', '?')}</span>
    <span>Generated: {now}</span>
    <span>Profile: <strong>{config.get('oppose_profile', '?')}</strong></span>
</div>

<div class="disclaimer">
    This report was generated automatically by <strong>monceai</strong> for audit and compliance purposes.
    Every prediction made by this model is fully explainable through SAT clause logic — no black-box decisions.
    Detailed per-datapoint audit traces are included in the <code>audit_traces/</code> directory.
</div>

<h2>1. Model Overview</h2>
<div class="stats-grid">
    <div class="stat"><div class="stat-value">{n_samples}</div><div class="stat-label">Training Samples</div></div>
    <div class="stat"><div class="stat-value">{len(features)}</div><div class="stat-label">Features</div></div>
    <div class="stat"><div class="stat-value">{len(classes)}</div><div class="stat-label">Classes</div></div>
    <div class="stat"><div class="stat-value">{n_layers}</div><div class="stat-label">SAT Layers</div></div>
</div>

<h3>Class Distribution</h3>
<table>
    <thead><tr><th>Class</th><th>Count</th><th>Proportion</th><th>Distribution</th></tr></thead>
    <tbody>{class_rows}</tbody>
</table>

<h3>Feature Profile</h3>
<table>
    <thead><tr><th>Feature</th><th>Type</th><th>Unique Values</th><th>Statistics</th></tr></thead>
    <tbody>{feature_rows}</tbody>
</table>

<h2>2. Training Configuration</h2>
<table>
    <thead><tr><th>Parameter</th><th>Value</th><th>Description</th></tr></thead>
    <tbody>
        <tr><td>n_layers</td><td><strong>{config.get('n_layers', '?')}</strong></td><td>Number of stochastic SAT ensemble layers</td></tr>
        <tr><td>bucket</td><td><strong>{config.get('bucket', '?')}</strong></td><td>Max samples per decision tree partition</td></tr>
        <tr><td>noise</td><td><strong>{config.get('noise', '?')}</strong></td><td>Cross-bucket regularization ratio</td></tr>
        <tr><td>oppose_profile</td><td><strong>{config.get('oppose_profile', '?')}</strong></td><td>Literal generation strategy (text/numeric weighting)</td></tr>
        <tr><td>target</td><td><strong>{model_card.get('target_column', '?')}</strong></td><td>Target column for classification</td></tr>
    </tbody>
</table>

{ranking_section}

{audit_section}

{perf_section}

<h2>{'6' if audit_traces else '4'}. Methodology</h2>
<p>This model uses the <strong>Snake algorithm</strong> — a SAT-based explainable multiclass classifier developed by Charles Dana (Monce SAS / Tulane University). Key properties:</p>
<ul style="margin: 12px 0 12px 24px; line-height: 2;">
    <li><strong>Explainability:</strong> Every prediction is backed by a conjunction of human-readable boolean literals (e.g., "size > 10 AND color contains 'red'"). No hidden weights or activations.</li>
    <li><strong>Dana Theorem:</strong> Any indicator function over a finite discrete domain can be encoded as a SAT instance in polynomial time. Snake constructs — not solves — SAT formulas from data.</li>
    <li><strong>Stochastic ensemble:</strong> {n_layers} independent layers, each with its own decision tree and SAT clause set. Predictions are majority-vote across layers.</li>
    <li><strong>Lookalike matching:</strong> Each prediction identifies the training samples (lookalikes) that share the same SAT clause structure as the input. These are the model's "reasoning by analogy."</li>
    <li><strong>Complexity:</strong> Training is O(L &times; n &times; m &times; b) — linear in samples and features. Inference is O(L &times; clauses).</li>
</ul>

<h2>{'7' if audit_traces else '5'}. Files in This Package</h2>
<table>
    <thead><tr><th>File</th><th>Description</th></tr></thead>
    <tbody>
        <tr><td><code>EXECUTIVE_SUMMARY.html</code></td><td>This report (print to PDF via browser)</td></tr>
        <tr><td><code>MODEL_CARD.json</code></td><td>Model metadata, config, feature list, class list</td></tr>
        <tr><td><code>TRAINING_PROFILE.json</code></td><td>Class distribution, feature statistics, data types</td></tr>
        <tr><td><code>COST_AND_PERFORMANCE.json</code></td><td>Training time, Lambda costs, inference latency</td></tr>
        <tr><td><code>model.json</code></td><td>Full Snake model (loadable with <code>algorithmeai.Snake</code>)</td></tr>
        <tr><td><code>ranked_results.csv</code></td><td>Test items scored and ranked by P({target_class or 'target'})</td></tr>
        <tr><td><code>audit_traces/SUMMARY.txt</code></td><td>One-line summary of all audited items</td></tr>
        <tr><td><code>audit_traces/NNN_class.txt</code></td><td>Full SAT audit trace per datapoint</td></tr>
    </tbody>
</table>

<div class="footer">
    Generated by <strong>monceai v0.2.0</strong> &nbsp;|&nbsp; Snake algorithm by Charles Dana &nbsp;|&nbsp; Monce SAS &nbsp;|&nbsp; {now}
</div>

</body>
</html>"""
