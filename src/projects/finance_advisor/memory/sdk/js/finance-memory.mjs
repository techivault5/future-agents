/**
 * Finance Advisor memory SDK — browser, Node and VS Code, zero dependencies.
 *
 * Mirrors the Python SDK (projects/finance_advisor/memory/sdk.py) method for
 * method, including the SHA-1 hashing embedder, so a memory written here embeds
 * to the *same vector* the Python side would produce. That is what makes the
 * two halves interchangeable: export() here imports there and vice versa.
 *
 *   import { FinanceMemorySDK } from './finance-memory.mjs';
 *   const sdk = new FinanceMemorySDK({ store: 'local' });   // localStorage
 *   sdk.remember('take_home=180000', { tags: ['profile'], sensitive: true });
 *   sdk.recall('what do I earn');
 *   sdk.advise('loans', { principal: 3500000, annualRatePct: 8.6, months: 240 });
 *
 * Educational only — no advice, no promises of return.
 */

export const DISCLAIMER = 'Educational content, not licensed financial advice.';

export const MemoryType = Object.freeze({
  WORKING: 'working',
  EPISODIC: 'episodic',
  SEMANTIC: 'semantic',
  PROCEDURAL: 'procedural',
  GRAPH: 'graph',
});

const DEFAULT_DIM = 256;
const WORKING_TTL_SECONDS = 3600;
const W_SIMILARITY = 0.55;
const W_KEYWORD = 0.2;
const W_RECENCY = 0.15;
const W_IMPORTANCE = 0.1;

// ── SHA-1 (synchronous, so embed() stays sync like the Python side) ─────────

function sha1Bytes(input) {
  const bytes = new TextEncoder().encode(input);
  const bitLen = bytes.length * 8;
  const withPad = new Uint8Array((((bytes.length + 8) >> 6) + 1) << 6);
  withPad.set(bytes);
  withPad[bytes.length] = 0x80;
  const view = new DataView(withPad.buffer);
  view.setUint32(withPad.length - 4, bitLen >>> 0, false);
  view.setUint32(withPad.length - 8, Math.floor(bitLen / 4294967296), false);

  let [h0, h1, h2, h3, h4] = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0];
  const w = new Int32Array(80);
  const rol = (v, n) => (v << n) | (v >>> (32 - n));

  for (let block = 0; block < withPad.length; block += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getInt32(block + i * 4, false);
    for (let i = 16; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    let [a, b, c, d, e] = [h0, h1, h2, h3, h4];
    for (let i = 0; i < 80; i++) {
      let f;
      let k;
      if (i < 20) {
        f = (b & c) | (~b & d);
        k = 0x5a827999;
      } else if (i < 40) {
        f = b ^ c ^ d;
        k = 0x6ed9eba1;
      } else if (i < 60) {
        f = (b & c) | (b & d) | (c & d);
        k = 0x8f1bbcdc;
      } else {
        f = b ^ c ^ d;
        k = 0xca62c1d6;
      }
      const temp = (rol(a, 5) + f + e + k + w[i]) | 0;
      e = d;
      d = c;
      c = rol(b, 30);
      b = a;
      a = temp;
    }
    h0 = (h0 + a) | 0;
    h1 = (h1 + b) | 0;
    h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0;
  }
  return [h0, h1, h2, h3, h4];
}

/** First four bytes of SHA-1(feature), big-endian, modulo dim — as in Python. */
export function bucketOf(feature, dim = DEFAULT_DIM) {
  return (sha1Bytes(feature)[0] >>> 0) % dim;
}

const TOKEN_RE = /[a-z0-9₹%]+/g;

/** Lowercase word tokens; identical tokenisation to the Python embedder. */
export function tokenize(text) {
  return String(text).toLowerCase().match(TOKEN_RE) || [];
}

/** Cosine similarity, 0 when either vector is empty or zero-length. */
export function cosine(a, b) {
  if (!a?.length || !b?.length || a.length !== b.length) return 0;
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/**
 * Finance synonym table — identical to aliases.py, applied at query time so the
 * lexical embedder still answers "what is my income" against "take_home=...".
 */
export const FINANCE_ALIASES = {
  income: ['take_home', 'salary', 'earn', 'earnings', 'pay', 'ctc'],
  salary: ['take_home', 'income', 'pay'],
  earn: ['income', 'take_home', 'salary'],
  take_home: ['income', 'salary', 'pay'],
  debt: ['loan', 'emi', 'borrowed', 'credit', 'card'],
  loan: ['debt', 'emi', 'mortgage', 'borrowed'],
  emi: ['loan', 'debt', 'instalment', 'installment'],
  house: ['home', 'property', 'flat', 'apartment', 'mortgage'],
  property: ['house', 'home', 'flat', 'real', 'estate'],
  sip: ['mutual', 'fund', 'systematic', 'investment'],
  fund: ['sip', 'mutual', 'scheme', 'nav'],
  invest: ['investment', 'sip', 'equity', 'portfolio'],
  gold: ['bullion', 'goldbees', 'metal'],
  silver: ['silverbees', 'metal'],
  crypto: ['bitcoin', 'btc', 'vda', 'ethereum'],
  bitcoin: ['crypto', 'btc', 'vda'],
  tax: ['taxes', 'ltcg', 'stcg', '80c', 'regime', 'tds'],
  taxes: ['tax', 'ltcg', 'stcg', '80c', 'regime'],
  gains: ['ltcg', 'stcg', 'capital', 'profit'],
  retire: ['retirement', 'nps', 'epf', 'pension'],
  emergency: ['buffer', 'reserve', 'rainy', 'fund'],
  save: ['saving', 'savings', 'surplus'],
  goal: ['target', 'plan', 'objective'],
  risk: ['tolerance', 'appetite', 'volatility'],
  insurance: ['term', 'health', 'cover', 'premium'],
};

/** Query tokens plus their finance aliases, de-duplicated. */
export function expandTokens(tokens) {
  const out = [...tokens];
  const seen = new Set(tokens);
  for (const token of tokens) {
    for (const alias of FINANCE_ALIASES[token] ?? []) {
      if (!seen.has(alias)) {
        seen.add(alias);
        out.push(alias);
      }
    }
  }
  return out;
}

/** Portable lexical embedder: word + char-trigram hashing, L2-normalised. */
export class HashingEmbedder {
  constructor(dim = DEFAULT_DIM) {
    this.dim = dim;
  }

  embed(text) {
    const vec = new Array(this.dim).fill(0);
    for (const token of tokenize(text)) {
      vec[bucketOf(`w:${token}`, this.dim)] += 1;
      const padded = ` ${token} `;
      for (let i = 0; i < padded.length - 2; i++) {
        vec[bucketOf(`c:${padded.slice(i, i + 3)}`, this.dim)] += 0.5;
      }
    }
    const norm = Math.sqrt(vec.reduce((s, v) => s + v * v, 0));
    return norm === 0 ? vec : vec.map((v) => v / norm);
  }
}

/**
 * Optional upgrade: Transformers.js embeddings (WebGPU when available, WASM
 * otherwise). Async by nature, so use `embedAsync` and pass vectors in.
 */
export class TransformersJsEmbedder {
  constructor(model = 'Xenova/all-MiniLM-L6-v2') {
    this.model = model;
    this.dim = 384;
    this._pipe = null;
  }

  async embedAsync(text) {
    if (!this._pipe) {
      const { pipeline } = await import('@huggingface/transformers');
      this._pipe = await pipeline('feature-extraction', this.model, { device: 'webgpu' });
    }
    const out = await this._pipe(text, { pooling: 'mean', normalize: true });
    return Array.from(out.data);
  }
}

// ── backends ────────────────────────────────────────────────────────────────

/** Ephemeral Map-backed store (Node, tests, VS Code sessions). */
export class InMemoryBackend {
  constructor() {
    this.records = new Map();
  }

  put(record) {
    this.records.set(record.id, record);
  }

  get(id) {
    return this.records.get(id) ?? null;
  }

  delete(id) {
    return this.records.delete(id);
  }

  scan({ subject, types, tags } = {}) {
    return [...this.records.values()].filter((r) => {
      if (subject && r.subject !== subject) return false;
      if (types?.length && !types.includes(r.type)) return false;
      if (tags?.length && !tags.some((t) => r.tags.includes(t))) return false;
      return true;
    });
  }

  count() {
    return this.records.size;
  }
}

/** Browser-durable store: one localStorage key, JSON-encoded. */
export class LocalStorageBackend extends InMemoryBackend {
  constructor(key = 'finance-advisor:memory') {
    super();
    this.key = key;
    this._load();
  }

  _load() {
    try {
      const raw = globalThis.localStorage?.getItem(this.key);
      if (raw) for (const rec of JSON.parse(raw)) this.records.set(rec.id, rec);
    } catch {
      /* corrupt or unavailable storage: start empty rather than throw */
    }
  }

  _flush() {
    try {
      globalThis.localStorage?.setItem(this.key, JSON.stringify([...this.records.values()]));
    } catch {
      /* quota or privacy mode: keep working in memory */
    }
  }

  put(record) {
    super.put(record);
    this._flush();
  }

  delete(id) {
    const existed = super.delete(id);
    this._flush();
    return existed;
  }
}

// ── memory manager ──────────────────────────────────────────────────────────

const nowIso = () => new Date().toISOString();
const randomId = () => Math.random().toString(16).slice(2, 14).padEnd(12, '0');

/** Same write/recall/maintain semantics and scoring weights as Python. */
export class MemoryManager {
  constructor({ backend, embedder, subject = 'user' } = {}) {
    this.backend = backend ?? new InMemoryBackend();
    this.embedder = embedder ?? new HashingEmbedder();
    this.subject = subject;
  }

  remember(content, options = {}) {
    const {
      type = MemoryType.SEMANTIC,
      tags = [],
      importance = 0.5,
      sensitive = false,
      source = 'user',
      relations = [],
      embedding = null,
    } = options;
    let ttlSeconds = options.ttlSeconds ?? null;
    if (type === MemoryType.WORKING && ttlSeconds === null) ttlSeconds = WORKING_TTL_SECONDS;
    const record = {
      id: randomId(),
      type,
      content: String(content),
      subject: this.subject,
      tags,
      importance,
      confidence: 1,
      ttl_seconds: ttlSeconds,
      source,
      sensitive,
      embedding: embedding ?? this.embedder.embed(content),
      relations,
      created_at: nowIso(),
      last_access: nowIso(),
      access_count: 0,
    };
    this.backend.put(record);
    return record;
  }

  static ageSeconds(record) {
    return (Date.now() - new Date(record.created_at).getTime()) / 1000;
  }

  static isExpired(record) {
    return record.ttl_seconds != null && MemoryManager.ageSeconds(record) > record.ttl_seconds;
  }

  static recencyScore(record, halfLifeSeconds = 7 * 24 * 3600) {
    return Math.pow(0.5, MemoryManager.ageSeconds(record) / halfLifeSeconds);
  }

  static redact(record) {
    return record.sensitive ? { ...record, content: '[redacted:sensitive]' } : record;
  }

  recall(query, { types = null, tags = null, limit = 5, includeExpired = false } = {}) {
    const expanded = expandTokens(tokenize(query));
    const queryVec = this.embedder.embed(expanded.join(' '));
    const queryTokens = new Set(expanded);
    const hits = [];
    for (const record of this.backend.scan({ subject: this.subject, types, tags })) {
      if (!includeExpired && MemoryManager.isExpired(record)) continue;
      const similarity = record.embedding?.length ? cosine(queryVec, record.embedding) : 0;
      const recordTokens = new Set(tokenize(record.content));
      let overlap = 0;
      for (const t of queryTokens) if (recordTokens.has(t)) overlap++;
      const keyword = queryTokens.size ? overlap / queryTokens.size : 0;
      const recency = MemoryManager.recencyScore(record);
      const score =
        W_SIMILARITY * similarity +
        W_KEYWORD * keyword +
        W_RECENCY * recency +
        W_IMPORTANCE * record.importance;
      hits.push({ record, score, similarity, keyword, recency });
    }
    hits.sort((a, b) => b.score - a.score);
    const top = hits.slice(0, limit);
    for (const hit of top) {
      hit.record.access_count += 1;
      hit.record.last_access = nowIso();
      this.backend.put(hit.record);
    }
    return top;
  }

  contextBlock(query, limit = 5) {
    const hits = this.recall(query, { limit });
    if (!hits.length) return '- (no prior memories)';
    return hits
      .map((h) => `- [${h.record.type}] ${MemoryManager.redact(h.record).content}`)
      .join('\n');
  }

  profile() {
    const out = {};
    for (const record of this.backend.scan({
      subject: this.subject,
      types: [MemoryType.SEMANTIC],
    })) {
      if (!record.tags.includes('profile')) continue;
      const idx = record.content.indexOf('=');
      if (idx > 0) out[record.content.slice(0, idx).trim()] = record.content.slice(idx + 1).trim();
    }
    return out;
  }

  consolidate(minOccurrences = 3) {
    const episodes = this.backend.scan({
      subject: this.subject,
      types: [MemoryType.EPISODIC],
    });
    if (episodes.length < minOccurrences) return [];
    const counts = new Map();
    for (const record of episodes) {
      for (const token of new Set(tokenize(record.content))) {
        if (token.length > 3) counts.set(token, (counts.get(token) ?? 0) + 1);
      }
    }
    const existing = new Set(
      this.backend
        .scan({ subject: this.subject, types: [MemoryType.SEMANTIC] })
        .map((r) => r.content),
    );
    const created = [];
    for (const [token, count] of counts) {
      if (count < minOccurrences) continue;
      const content = `recurring_interest=${token} (seen in ${count} interactions)`;
      if (existing.has(content)) continue;
      created.push(
        this.remember(content, {
          type: MemoryType.SEMANTIC,
          tags: ['consolidated', 'profile'],
          importance: Math.min(0.4 + 0.1 * count, 0.9),
          source: 'agent',
        }),
      );
    }
    return created;
  }

  forget(minImportance = 0.15) {
    let removed = 0;
    for (const record of this.backend.scan({ subject: this.subject })) {
      const worthless = record.importance < minImportance && record.access_count === 0;
      if (MemoryManager.isExpired(record) || worthless) {
        if (this.backend.delete(record.id)) removed++;
      }
    }
    return removed;
  }

  stats() {
    const records = this.backend.scan({ subject: this.subject });
    const byType = {};
    for (const r of records) byType[r.type] = (byType[r.type] ?? 0) + 1;
    return {
      total: records.length,
      by_type: byType,
      sensitive: records.filter((r) => r.sensitive).length,
      embedder: this.embedder.constructor.name,
      embedding_dim: this.embedder.dim,
      backend: this.backend.constructor.name,
    };
  }

  export(redact = true) {
    return this.backend.scan({ subject: this.subject }).map((record) => {
      const item = { ...(redact ? MemoryManager.redact(record) : record) };
      delete item.embedding;
      return item;
    });
  }

  importRecords(items) {
    let loaded = 0;
    for (const item of items) {
      const record = { ...item, embedding: this.embedder.embed(item.content) };
      this.backend.put(record);
      loaded++;
    }
    return loaded;
  }
}

// ── finance skills (same maths as the Python skills) ─────────────────────────

const EQUITY_LTCG_RATE = 0.125;
const EQUITY_LTCG_EXEMPTION = 125000;
const EQUITY_STCG_RATE = 0.2;
const EQUITY_LTCG_HOLDING_MONTHS = 12;
const VDA_TAX_RATE = 0.3;
const VDA_TDS_RATE = 0.01;
const SECTION_80C_CAP = 150000;
const NPS_80CCD1B_CAP = 50000;

const round2 = (n) => Math.round(n * 100) / 100;

export const loans = {
  name: 'loans',
  covers: 'EMI, affordability, prepayment vs investing, avalanche vs snowball',

  emi(principal, annualRatePct, months) {
    if (months <= 0) throw new Error('months must be positive');
    const r = annualRatePct / 12 / 100;
    if (r === 0) return principal / months;
    const f = Math.pow(1 + r, months);
    return (principal * r * f) / (f - 1);
  },

  affordability(monthlyTakeHome, existingEmi = 0) {
    const ceiling = 0.4 * monthlyTakeHome;
    return {
      total_emi_ceiling: round2(ceiling),
      housing_emi_ceiling: round2(0.3 * monthlyTakeHome),
      existing_emi: round2(existingEmi),
      headroom: round2(Math.max(ceiling - existingEmi, 0)),
      rule: 'Total EMIs ≤40% of take-home; housing alone ≤30%.',
    };
  },

  payoffOrder(debts) {
    const aprs = debts.map((d) => Number(d.apr) || 0);
    const spread = Math.max(...aprs) - Math.min(...aprs);
    return {
      avalanche_order: [...debts].sort((a, b) => b.apr - a.apr).map((d) => d.name),
      snowball_order: [...debts].sort((a, b) => a.balance - b.balance).map((d) => d.name),
      apr_spread_pct: round2(spread),
      recommended: spread >= 4 ? 'avalanche' : 'snowball (APRs are close)',
    };
  },

  advise(args = {}) {
    if (args.debts) return { skill: 'loans', ...loans.payoffOrder(args.debts), disclaimer: DISCLAIMER };
    if (args.monthlyTakeHome != null) {
      return {
        skill: 'loans',
        ...loans.affordability(args.monthlyTakeHome, args.existingEmi ?? 0),
        disclaimer: DISCLAIMER,
      };
    }
    const principal = Number(args.principal ?? 0);
    const months = Number(args.months ?? 240);
    const rate = Number(args.annualRatePct ?? 9);
    const payment = loans.emi(principal, rate, months);
    return {
      skill: 'loans',
      principal,
      annual_rate_pct: rate,
      months,
      emi: round2(payment),
      total_paid: round2(payment * months),
      total_interest: round2(payment * months - principal),
      disclaimer: DISCLAIMER,
    };
  },
};

export const mutualFunds = {
  name: 'mutual_funds',
  covers: 'SIP future value, step-up SIP, goal planning, direct-vs-regular cost drag',

  sipFutureValue(monthly, annualReturnPct, years) {
    const i = annualReturnPct / 12 / 100;
    const n = years * 12;
    if (i === 0) return monthly * n;
    return monthly * ((Math.pow(1 + i, n) - 1) / i) * (1 + i);
  },

  requiredSip(target, annualReturnPct, years) {
    const i = annualReturnPct / 12 / 100;
    const n = years * 12;
    if (i === 0) return target / n;
    return target / (((Math.pow(1 + i, n) - 1) / i) * (1 + i));
  },

  advise(args = {}) {
    const years = Number(args.years ?? 15);
    const expected = Number(args.annualReturnPct ?? 12);
    if (args.target != null) {
      return {
        skill: 'mutual_funds',
        target: Number(args.target),
        years,
        assumed_return_pct: expected,
        required_monthly_sip: round2(mutualFunds.requiredSip(Number(args.target), expected, years)),
        disclaimer: DISCLAIMER,
      };
    }
    const monthly = Number(args.monthly ?? 10000);
    const fv = mutualFunds.sipFutureValue(monthly, expected, years);
    const invested = monthly * years * 12;
    return {
      skill: 'mutual_funds',
      monthly,
      years,
      assumed_return_pct: expected,
      invested: round2(invested),
      future_value: round2(fv),
      gain: round2(fv - invested),
      category_guidance:
        'Core 70-80% flexi/large-cap or broad index; satellite 20-30% mid/small or ' +
        'international. Direct plans, growth option.',
      disclaimer: DISCLAIMER,
    };
  },
};

export const crypto = {
  name: 'crypto',
  covers: 'allocation caps, 30% VDA tax + 1% TDS maths, custody, scam checks',

  positionCap(portfolioValue, riskTolerance = 'moderate') {
    const caps = { conservative: 0, moderate: 0.05, aggressive: 0.1 };
    const pct = caps[riskTolerance] ?? 0.05;
    return {
      risk_tolerance: riskTolerance,
      cap_pct: pct * 100,
      cap_amount: round2(portfolioValue * pct),
    };
  },

  afterTaxGain(buyValue, sellValue) {
    const gain = sellValue - buyValue;
    return {
      gross_gain: round2(gain),
      vda_tax_30pct: round2(Math.max(gain, 0) * VDA_TAX_RATE),
      tds_1pct_on_sale: round2(sellValue * VDA_TDS_RATE),
      net_gain_after_tax: round2(gain - Math.max(gain, 0) * VDA_TAX_RATE),
      note: 'No loss set-off against other income or other VDA trades in India.',
    };
  },

  advise(args = {}) {
    if (args.sellValue != null) {
      return {
        skill: 'crypto',
        ...crypto.afterTaxGain(Number(args.buyValue ?? 0), Number(args.sellValue)),
        disclaimer: DISCLAIMER,
      };
    }
    return {
      skill: 'crypto',
      ...crypto.positionCap(Number(args.portfolioValue ?? 0), args.riskTolerance ?? 'moderate'),
      custody: 'Hardware wallet for meaningful holdings; seed phrase offline only.',
      disclaimer: DISCLAIMER,
    };
  },
};

export const capitalGains = {
  name: 'capital_gains',
  covers: 'LTCG 12.5% above ₹1.25L, STCG 20%, holding period, exemption harvesting',

  equityGainTax(buyValue, sellValue, holdingMonths, priorLtcgUsed = 0) {
    const gain = sellValue - buyValue;
    const longTerm = holdingMonths >= EQUITY_LTCG_HOLDING_MONTHS;
    if (gain <= 0) {
      return { gain: round2(gain), classification: longTerm ? 'long-term' : 'short-term', tax: 0 };
    }
    if (longTerm) {
      const room = Math.max(EQUITY_LTCG_EXEMPTION - priorLtcgUsed, 0);
      const taxable = Math.max(gain - room, 0);
      return {
        gain: round2(gain),
        classification: 'long-term',
        exemption_applied: round2(Math.min(gain, room)),
        taxable_gain: round2(taxable),
        rate_pct: EQUITY_LTCG_RATE * 100,
        tax: round2(taxable * EQUITY_LTCG_RATE),
      };
    }
    return {
      gain: round2(gain),
      classification: 'short-term',
      taxable_gain: round2(gain),
      rate_pct: EQUITY_STCG_RATE * 100,
      tax: round2(gain * EQUITY_STCG_RATE),
    };
  },

  advise(args = {}) {
    if (args.sellValue != null) {
      return {
        skill: 'capital_gains',
        ...capitalGains.equityGainTax(
          Number(args.buyValue ?? 0),
          Number(args.sellValue),
          Number(args.holdingMonths ?? 0),
          Number(args.priorLtcgUsed ?? 0),
        ),
        disclaimer: DISCLAIMER,
      };
    }
    const room = Math.max(EQUITY_LTCG_EXEMPTION - Number(args.priorLtcgUsed ?? 0), 0);
    return {
      skill: 'capital_gains',
      exemption_room: round2(room),
      harvestable_now: round2(Math.min(Number(args.unrealisedLtcg ?? 0), room)),
      disclaimer: DISCLAIMER,
    };
  },
};

export const taxes = {
  name: 'taxes',
  covers: 'old vs new regime pointers, 80C/80CCD capacity, asset-wise treatment',

  deductionCapacity(existing80c = 0, hasNps = false, regime = 'new') {
    if (regime === 'new') {
      return {
        regime: 'new',
        section_80c_room: 0,
        note: 'The new regime forgoes 80C/80CCD(1B); pick ELSS/NPS on merit alone.',
      };
    }
    return {
      regime: 'old',
      section_80c_cap: SECTION_80C_CAP,
      section_80c_room: round2(Math.max(SECTION_80C_CAP - existing80c, 0)),
      nps_80ccd1b_room: hasNps ? 0 : NPS_80CCD1B_CAP,
    };
  },

  advise(args = {}) {
    return {
      skill: 'taxes',
      ...taxes.deductionCapacity(
        Number(args.existing80c ?? 0),
        Boolean(args.hasNps),
        args.regime ?? 'new',
      ),
      vda: `Crypto: flat ${VDA_TAX_RATE * 100}% + ${VDA_TDS_RATE * 100}% TDS, no set-off.`,
      escalate: 'Property gains, ESOPs, foreign assets: see a chartered accountant.',
      disclaimer: DISCLAIMER,
    };
  },
};

export const SKILLS = { loans, mutual_funds: mutualFunds, crypto, capital_gains: capitalGains, taxes };

/** Compute targets a browser/Node host can reach, mirroring runtimes.py. */
export const RUNTIME_MATRIX = [
  {
    name: 'HashingEmbedder (this SDK)',
    target: 'cpu',
    runs_where: 'Anywhere JS runs — browser, Node, VS Code',
    good_for: 'Zero-install lexical recall; identical vectors to the Python SDK',
    setup_effort: 'none',
    offline: true,
  },
  {
    name: 'Transformers.js (ONNX Runtime Web)',
    target: 'browser',
    runs_where: 'WebGPU when available, WASM fallback',
    good_for: 'Real semantic embeddings client-side; v4 WebGPU rewrite is ~4x faster',
    setup_effort: 'low',
    offline: true,
  },
  {
    name: 'Ollama (localhost)',
    target: 'gpu',
    runs_where: 'Local Ollama server on the same machine',
    good_for: 'Better embeddings without shipping weights to the page',
    setup_effort: 'low',
    offline: true,
  },
];

/** Facade mirroring the Python FinanceMemorySDK. */
export class FinanceMemorySDK {
  constructor({ store = 'memory', key, embedder, subject = 'user' } = {}) {
    const backend = store === 'local' ? new LocalStorageBackend(key) : new InMemoryBackend();
    this.memory = new MemoryManager({ backend, embedder, subject });
  }

  remember(content, options) {
    return MemoryManager.redact(this.memory.remember(content, options));
  }

  recall(query, limit = 5, type = null) {
    return this.memory
      .recall(query, { limit, types: type ? [type] : null })
      .map((hit) => ({
        content: MemoryManager.redact(hit.record).content,
        type: hit.record.type,
        tags: hit.record.tags,
        score: round2(hit.score * 10000) / 10000,
        similarity: hit.similarity,
        keyword: hit.keyword,
        recency: hit.recency,
      }));
  }

  context(query, limit = 5) {
    return this.memory.contextBlock(query, limit);
  }

  profile() {
    return this.memory.profile();
  }

  consolidate(minOccurrences = 3) {
    return this.memory.consolidate(minOccurrences).length;
  }

  forget() {
    return this.memory.forget();
  }

  stats() {
    return this.memory.stats();
  }

  export() {
    return this.memory.export();
  }

  importRecords(items) {
    return this.memory.importRecords(items);
  }

  skill(name) {
    const found = SKILLS[name];
    if (!found) throw new Error(`unknown skill '${name}'; available: ${Object.keys(SKILLS)}`);
    return found;
  }

  advise(name, args = {}) {
    const result = this.skill(name).advise(args);
    result.memory_context = this.context(name, 3);
    return result;
  }

  static skills() {
    return Object.values(SKILLS).map((s) => ({ name: s.name, covers: s.covers }));
  }

  static runtimes() {
    return RUNTIME_MATRIX;
  }

  static capabilities() {
    const hasWebGpu = typeof navigator !== 'undefined' && 'gpu' in navigator;
    return {
      environment: typeof window === 'undefined' ? 'node' : 'browser',
      webgpu: hasWebGpu,
      localStorage: typeof globalThis.localStorage !== 'undefined',
      recommended: hasWebGpu
        ? 'TransformersJsEmbedder (WebGPU) for semantic recall'
        : 'HashingEmbedder (portable, zero-install)',
    };
  }
}

export default FinanceMemorySDK;
