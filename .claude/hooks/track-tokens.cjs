#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');

// Tiered pricing: tokens above 200k threshold are charged at a higher rate
const THRESHOLD = 200000;
function tieredCost(tokens, baseRate, aboveRate) {
  if (tokens <= 0) return 0;
  if (tokens > THRESHOLD && aboveRate) {
    return Math.min(tokens, THRESHOLD) * baseRate + Math.max(0, tokens - THRESHOLD) * aboveRate;
  }
  return tokens * baseRate;
}

// Model pricing per token (ccusage-style, supports tiered pricing)
const PRICING = {
  opus:   { input: 15e-6, output: 75e-6, cacheWrite: 18.75e-6, cacheRead: 1.5e-6,
            inputAbove200k: 30e-6, outputAbove200k: 112.5e-6, cacheWriteAbove200k: 37.5e-6, cacheReadAbove200k: 3e-6 },
  sonnet: { input: 3e-6, output: 15e-6, cacheWrite: 3.75e-6, cacheRead: 0.3e-6,
            inputAbove200k: 6e-6, outputAbove200k: 22.5e-6, cacheWriteAbove200k: 7.5e-6, cacheReadAbove200k: 0.6e-6 },
  haiku:  { input: 0.8e-6, output: 4e-6, cacheWrite: 1e-6, cacheRead: 0.08e-6 },
};

function getPricing(modelName) {
  const m = modelName.toLowerCase();
  if (m.includes('opus')) return PRICING.opus;
  if (m.includes('haiku')) return PRICING.haiku;
  return PRICING.sonnet;
}

let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  try {
    const event = JSON.parse(input);
    const transcriptPath = event.transcript_path;
    const sessionId = event.session_id || 'unknown';

    if (!transcriptPath || !fs.existsSync(transcriptPath)) process.exit(0);

    // Per-model aggregation (like ccusage's aggregateByModel)
    const models = {};
    const seen = new Set();

    function processLines(text) {
      for (const line of text.split('\n')) {
        if (!line.trim()) continue;
        try {
          const obj = JSON.parse(line);
          const msg = obj.message;
          if (!msg || !msg.usage) continue;
          const u = msg.usage;
          // Skip zero-usage entries (e.g. <synthetic>)
          if (!u.input_tokens && !u.output_tokens && !u.cache_creation_input_tokens && !u.cache_read_input_tokens) continue;
          // Dedup by messageId:requestId
          const dedup = (msg.id || '') + ':' + (obj.requestId || '');
          if (dedup !== ':' && seen.has(dedup)) continue;
          if (dedup !== ':') seen.add(dedup);
          const model = msg.model || 'unknown';
          if (!models[model]) models[model] = { inputTokens: 0, outputTokens: 0, cacheCreate: 0, cacheRead: 0 };
          models[model].inputTokens  += u.input_tokens || 0;
          models[model].outputTokens += u.output_tokens || 0;
          models[model].cacheCreate  += u.cache_creation_input_tokens || 0;
          models[model].cacheRead    += u.cache_read_input_tokens || 0;
        } catch {}
      }
    }

    // Read main session transcript
    processLines(fs.readFileSync(transcriptPath, 'utf8'));

    // Also read subagent JSONL files — subagents use separate API sessions
    // stored at <transcriptPath without .jsonl>/subagents/*.jsonl
    const sessionDir = transcriptPath.replace(/\.jsonl$/, '');
    const subagentDir = path.join(sessionDir, 'subagents');
    if (fs.existsSync(subagentDir)) {
      try {
        const subFiles = fs.readdirSync(subagentDir).filter(f => f.endsWith('.jsonl'));
        for (const sf of subFiles) {
          try { processLines(fs.readFileSync(path.join(subagentDir, sf), 'utf8')); } catch {}
        }
      } catch {}
    }

    // Calculate cost per model with tiered pricing
    let totalCost = 0;
    let totalInput = 0, totalOutput = 0, totalCacheCreate = 0, totalCacheRead = 0;
    const modelBreakdowns = [];
    let primaryModel = 'unknown';
    let maxTokens = 0;

    for (const [model, t] of Object.entries(models)) {
      const p = getPricing(model);
      const cost = tieredCost(t.inputTokens, p.input, p.inputAbove200k)
                 + tieredCost(t.outputTokens, p.output, p.outputAbove200k)
                 + tieredCost(t.cacheCreate, p.cacheWrite, p.cacheWriteAbove200k)
                 + tieredCost(t.cacheRead, p.cacheRead, p.cacheReadAbove200k);
      totalCost += cost;
      totalInput += t.inputTokens;
      totalOutput += t.outputTokens;
      totalCacheCreate += t.cacheCreate;
      totalCacheRead += t.cacheRead;
      const total = t.inputTokens + t.outputTokens + t.cacheCreate + t.cacheRead;
      if (total > maxTokens) { maxTokens = total; primaryModel = model; }
      modelBreakdowns.push({ model, ...t, cost, totalTokens: total });
    }

    const record = {
      sessionId,
      timestamp: new Date().toISOString(),
      model: primaryModel,
      inputTokens: totalInput,
      outputTokens: totalOutput,
      cacheCreate: totalCacheCreate,
      cacheRead: totalCacheRead,
      cost: totalCost,
      modelBreakdowns
    };

    const usageFile = path.join(process.cwd(), '.claude', 'token-usage.json');
    let records = [];
    try { records = JSON.parse(fs.readFileSync(usageFile, 'utf8')); } catch {}
    const idx = records.findIndex(r => r.sessionId === sessionId);
    if (idx >= 0) { records[idx] = record; } else { records.push(record); }
    if (records.length > 100) records = records.slice(-100);
    const dir = path.dirname(usageFile);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(usageFile, JSON.stringify(records, null, 2));
  } catch { process.exit(0); }
});
