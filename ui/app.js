const state = {
  address: null,
  me: null,
  selectedMarket: null,
  lastEntry: null,
  lastArmId: null,
  tokenMetaByTokenId: {},
};

const ZERO = "0x0000000000000000000000000000000000000000";
const ORDER_TYPES = {
  EIP712Domain: [
    { name: "name", type: "string" },
    { name: "version", type: "string" },
    { name: "chainId", type: "uint256" },
    { name: "verifyingContract", type: "address" },
  ],
  Order: [
    { name: "salt", type: "uint256" },
    { name: "maker", type: "address" },
    { name: "signer", type: "address" },
    { name: "taker", type: "address" },
    { name: "tokenId", type: "uint256" },
    { name: "makerAmount", type: "uint256" },
    { name: "takerAmount", type: "uint256" },
    { name: "expiration", type: "uint256" },
    { name: "nonce", type: "uint256" },
    { name: "feeRateBps", type: "uint256" },
    { name: "side", type: "uint8" },
    { name: "signatureType", type: "uint8" },
  ],
};

const CLOB_AUTH_TYPES = {
  EIP712Domain: [
    { name: "name", type: "string" },
    { name: "version", type: "string" },
    { name: "chainId", type: "uint256" },
  ],
  ClobAuth: [
    { name: "address", type: "address" },
    { name: "timestamp", type: "string" },
    { name: "nonce", type: "uint256" },
    { name: "message", type: "string" },
  ],
};

const CHAIN_PARAMS_BY_ID = {
  137: {
    chainId: "0x89",
    chainName: "Polygon Mainnet",
    nativeCurrency: { name: "MATIC", symbol: "MATIC", decimals: 18 },
    rpcUrls: ["https://polygon-rpc.com"],
    blockExplorerUrls: ["https://polygonscan.com"],
  },
};

const ROUNDING_CONFIG_BY_TICK = {
  "0.1": { price: 1, size: 2, amount: 3 },
  "0.01": { price: 2, size: 2, amount: 4 },
  "0.001": { price: 3, size: 2, amount: 5 },
  "0.0001": { price: 4, size: 2, amount: 6 },
};

const $ = (id) => document.getElementById(id);

function setText(id, text) {
  $(id).textContent = text;
}

function setJSON(id, value) {
  $(id).textContent = JSON.stringify(value, null, 2);
}

const BALANCE_AVAILABLE_KEYS = new Set([
  "available",
  "available_balance",
  "available_usdc",
  "usdc_available",
  "free",
  "free_balance",
  "spendable",
  "buying_power",
  "buyingpower",
]);

const BALANCE_TOTAL_KEYS = new Set([
  "balance",
  "total",
  "total_balance",
  "total_usdc",
  "usdc_balance",
  "cash_balance",
  "collateral",
  "equity",
]);

function normalizeKey(value) {
  return String(value || "").trim().toLowerCase().replaceAll("-", "_");
}

function toNumber(value) {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    let text = value.trim().replaceAll(",", "");
    if (text.startsWith("$")) {
      text = text.slice(1);
    }
    if (!text) {
      return null;
    }
    const parsed = Number(text);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function toPositiveNumberOrNull(value) {
  const n = toNumber(value);
  if (n === null || !Number.isFinite(n) || n <= 0) {
    return null;
  }
  return n;
}

function findFirstNumericByKeys(obj, keys) {
  if (!obj || typeof obj !== "object") {
    return null;
  }

  if (Array.isArray(obj)) {
    for (const item of obj) {
      const nested = findFirstNumericByKeys(item, keys);
      if (nested !== null) {
        return nested;
      }
    }
    return null;
  }

  for (const [key, value] of Object.entries(obj)) {
    if (keys.has(normalizeKey(key))) {
      const n = toNumber(value);
      if (n !== null) {
        return n;
      }
    }
  }

  for (const value of Object.values(obj)) {
    const nested = findFirstNumericByKeys(value, keys);
    if (nested !== null) {
      return nested;
    }
  }

  return null;
}

function formatUsdc(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "N/A";
  }
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function getWalletSummary() {
  const ctx = state.me?.trading_context || {};
  const summary = ctx.wallet_summary || {};

  let available = toNumber(summary.available_usdc);
  let total = toNumber(summary.total_usdc);

  if (available === null || total === null) {
    const raw = ctx.dome_wallet;
    if (available === null) {
      available = findFirstNumericByKeys(raw, BALANCE_AVAILABLE_KEYS);
    }
    if (total === null) {
      total = findFirstNumericByKeys(raw, BALANCE_TOTAL_KEYS);
    }
  }

  return { available, total };
}

function renderWalletSummary() {
  const box = $("walletSummary");
  if (!state.me) {
    box.textContent = "";
    return;
  }

  const ctx = state.me.trading_context || {};
  const { available, total } = getWalletSummary();
  const lines = [];

  if (ctx.mode === "proxy") {
    lines.push(`Proxy/Safe: ${ctx.trading_address || "N/A"}`);
  }

  if (available !== null) {
    lines.push(`Available USDC: ${formatUsdc(available)}`);
  }

  if (total !== null) {
    lines.push(`Total USDC: ${formatUsdc(total)}`);
  }

  if (!lines.length) {
    lines.push("Balance was not returned by provider for this wallet.");
  }

  box.textContent = lines.join("\n");
}

function marketQuestionText(market) {
  return String(market?.question || market?.title || "").trim();
}

function outcomeLabel(market, side) {
  const raw = side === "YES" ? market?.yes_label : market?.no_label;
  const text = String(raw || "").trim();
  return text || null;
}

function updateMarketUiState() {
  const market = state.selectedMarket;
  const outcome = $("outcome").value;
  const yesOption = $("outcome").querySelector("option[value='YES']");
  const noOption = $("outcome").querySelector("option[value='NO']");

  if (!market) {
    yesOption.textContent = "BUY YES";
    noOption.textContent = "BUY NO";
    setText("tokenStatus", "Select a market first.");
    setText("marketQuestion", "");
    setText("outcomeMeaning", "YES = market resolves TRUE. NO = market resolves FALSE.");
    $("btnPlaceEntry").disabled = true;
    return;
  }

  const yesLabel = outcomeLabel(market, "YES");
  const noLabel = outcomeLabel(market, "NO");
  yesOption.textContent = yesLabel ? `BUY YES (${yesLabel})` : "BUY YES";
  noOption.textContent = noLabel ? `BUY NO (${noLabel})` : "BUY NO";

  const hasYesToken = Boolean(market.yes_token_id && market.yes_token_id !== "None");
  const hasNoToken = Boolean(market.no_token_id && market.no_token_id !== "None");

  if (hasYesToken && hasNoToken) {
    setText("tokenStatus", "Tokens are available for both outcomes. Market is tradable.");
    $("btnPlaceEntry").disabled = false;
  } else {
    setText(
      "tokenStatus",
      "Token IDs are missing for this market. Usually this means market is not open for CLOB trading yet.",
    );
    $("btnPlaceEntry").disabled = true;
  }

  const question = marketQuestionText(market);
  setText(
    "marketQuestion",
    question ? `Market question: ${question}` : "Market question is unavailable from provider response.",
  );

  const selectedLabel = outcomeLabel(market, outcome);
  const generic =
    outcome === "YES"
      ? "BUY YES means you buy the outcome where market question resolves TRUE."
      : "BUY NO means you buy the outcome where market question resolves FALSE.";
  const detail = selectedLabel
    ? ` Current selection maps to: ${selectedLabel}.`
    : " Provider did not return explicit YES/NO labels.";
  setText("outcomeMeaning", `${generic}${detail}`);
}

function selectMarket(market) {
  state.selectedMarket = market;
  $("marketId").value = market?.market_id || "";
  $("marketTitle").value = market?.title || "";
  $("yesToken").value = market?.yes_token_id || "";
  $("noToken").value = market?.no_token_id || "";
  updateMarketUiState();
}

function roundDown(value, digits) {
  const p = 10 ** Number(digits || 0);
  return Math.floor(Number(value) * p) / p;
}

function roundNormal(value, digits) {
  const p = 10 ** Number(digits || 0);
  return Math.round(Number(value) * p) / p;
}

function roundUp(value, digits) {
  const p = 10 ** Number(digits || 0);
  return Math.ceil(Number(value) * p) / p;
}

function decimalPlaces(value) {
  const text = String(value).toLowerCase();
  if (text.includes("e-")) {
    const [base, expText] = text.split("e-");
    const frac = (base.split(".")[1] || "").length;
    const exp = Number(expText || 0);
    return frac + exp;
  }
  const frac = text.split(".")[1] || "";
  return frac.length;
}

function toTokenDecimals(value) {
  const scaled = Number(value) * 1_000_000;
  if (!Number.isFinite(scaled)) {
    throw new Error(`Invalid token amount: ${value}`);
  }
  return String(Math.round(scaled));
}

function getRoundConfig(tickSize) {
  const key = String(tickSize || "0.01");
  return ROUNDING_CONFIG_BY_TICK[key] || ROUNDING_CONFIG_BY_TICK["0.01"];
}

function validatePriceAgainstTick(price, tickSize) {
  const tick = Number(tickSize);
  if (!Number.isFinite(tick) || tick <= 0 || tick >= 1) {
    return;
  }
  if (price < tick || price > 1 - tick) {
    throw new Error(`Price ${price} must be between ${tick} and ${1 - tick} for tick ${tick}.`);
  }
}

function computeOrderAmounts({ side, sizeTokens, price, tickSize }) {
  const cfg = getRoundConfig(tickSize);
  const rawPrice = roundNormal(Number(price), cfg.price);
  const rawSize = roundDown(Number(sizeTokens), cfg.size);

  if (!(rawPrice > 0 && rawPrice < 1)) {
    throw new Error(`Invalid rounded price: ${rawPrice}`);
  }
  if (!(rawSize > 0)) {
    throw new Error(`Order size is too small after rounding: ${rawSize}`);
  }

  let rawMaker;
  let rawTaker;

  if (side === "BUY") {
    rawTaker = rawSize;
    rawMaker = rawTaker * rawPrice;
    if (decimalPlaces(rawMaker) > cfg.amount) {
      rawMaker = roundUp(rawMaker, cfg.amount + 4);
      if (decimalPlaces(rawMaker) > cfg.amount) {
        rawMaker = roundDown(rawMaker, cfg.amount);
      }
    }
  } else if (side === "SELL") {
    rawMaker = rawSize;
    rawTaker = rawMaker * rawPrice;
    if (decimalPlaces(rawTaker) > cfg.amount) {
      rawTaker = roundUp(rawTaker, cfg.amount + 4);
      if (decimalPlaces(rawTaker) > cfg.amount) {
        rawTaker = roundDown(rawTaker, cfg.amount);
      }
    }
  } else {
    throw new Error(`Unsupported side: ${side}`);
  }

  return {
    makerAmount: toTokenDecimals(rawMaker),
    takerAmount: toTokenDecimals(rawTaker),
    normalizedPrice: rawPrice,
    normalizedSizeTokens: rawSize,
  };
}

function randomSalt() {
  // Keep salt within JS safe-integer range because CLOB expects JSON number.
  const now = Math.floor(Date.now() / 1000);
  const rand = Math.floor(Math.random() * 1_000_000);
  return String(now * rand);
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const text = await resp.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
  }

  if (!resp.ok) {
    const detail =
      data?.detail ||
      data?.error ||
      data?.message ||
      data?.raw ||
      text ||
      `HTTP ${resp.status}`;
    throw new Error(detail);
  }

  return data;
}

async function getConnectedAddress() {
  if (!window.ethereum) {
    throw new Error("No injected wallet found. Install MetaMask.");
  }

  const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
  if (!accounts || !accounts.length) {
    throw new Error("Wallet did not return an address.");
  }

  return accounts[0];
}

async function getActiveChainId() {
  const raw = await window.ethereum.request({ method: "eth_chainId" });
  if (typeof raw !== "string" || !raw.startsWith("0x")) {
    throw new Error(`Unexpected eth_chainId response: ${String(raw)}`);
  }
  const chainId = Number.parseInt(raw, 16);
  if (!Number.isInteger(chainId) || chainId <= 0) {
    throw new Error(`Invalid active chainId: ${raw}`);
  }
  return chainId;
}

async function ensureWalletChain(expectedChainId) {
  if (!window.ethereum) {
    throw new Error("No injected wallet found. Install MetaMask.");
  }

  const target = Number(expectedChainId);
  if (!Number.isInteger(target) || target <= 0) {
    return;
  }

  const active = await getActiveChainId();
  if (active === target) {
    return;
  }

  const targetHex = `0x${target.toString(16)}`;
  try {
    await window.ethereum.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: targetHex }],
    });
  } catch (err) {
    const code = Number(err?.code);
    const params = CHAIN_PARAMS_BY_ID[target];
    if (code === 4902 && params) {
      await window.ethereum.request({
        method: "wallet_addEthereumChain",
        params: [params],
      });
      await window.ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: targetHex }],
      });
    } else {
      const msg = err?.message ? ` ${err.message}` : "";
      throw new Error(
        `Switch wallet network to chainId ${target}. Active chainId is ${active}.${msg}`,
      );
    }
  }

  const activeAfter = await getActiveChainId();
  if (activeAfter !== target) {
    throw new Error(`Wallet chainId is ${activeAfter}, expected ${target}.`);
  }
}

async function signPersonal(address, message) {
  return window.ethereum.request({
    method: "personal_sign",
    params: [message, address],
  });
}

async function signTypedDataV4(address, typedData) {
  const expectedChainId = Number(typedData?.domain?.chainId);
  if (Number.isInteger(expectedChainId) && expectedChainId > 0) {
    await ensureWalletChain(expectedChainId);
  }
  return window.ethereum.request({
    method: "eth_signTypedData_v4",
    params: [address, JSON.stringify(typedData)],
  });
}

async function refreshMe() {
  state.me = await api("/api/me", { method: "GET" });
  setJSON("meBox", state.me);
  setText(
    "authState",
    `EOA: ${state.me.eoa_address}\nMode: ${state.me.trading_context.mode}\nTrading: ${state.me.trading_context.trading_address}`,
  );
  renderWalletSummary();
  updateMarketUiState();
}

async function handleConnect() {
  try {
    setText("authState", "Connecting wallet...");
    const address = await getConnectedAddress();
    state.address = address;

    const nonceData = await api("/api/auth/nonce", {
      method: "POST",
      body: JSON.stringify({ address }),
    });

    const signature = await signPersonal(address, nonceData.message);

    const clobAuthTimestamp = Math.floor(Date.now() / 1000);
    const clobAuthNonce = Math.floor(Math.random() * 1_000_000_000);
    const clobAuthTyped = {
      types: CLOB_AUTH_TYPES,
      primaryType: "ClobAuth",
      domain: {
        name: "ClobAuthDomain",
        version: "1",
        chainId: nonceData.chain_id,
      },
      message: {
        address,
        timestamp: String(clobAuthTimestamp),
        nonce: clobAuthNonce,
        message: "This message attests that I control the given wallet",
      },
    };

    const clobAuthSignature = await signTypedDataV4(address, clobAuthTyped);

    await api("/api/auth/verify", {
      method: "POST",
      body: JSON.stringify({
        address,
        nonce: nonceData.nonce,
        message: nonceData.message,
        signature,
        chain_id: nonceData.chain_id,
        clob_auth_signature: clobAuthSignature,
        clob_auth_timestamp: clobAuthTimestamp,
        clob_auth_nonce: clobAuthNonce,
      }),
    });

    await refreshMe();
  } catch (err) {
    setText("authState", `Auth failed: ${err.message}`);
    setText("walletSummary", "");
  }
}

function renderSearchResults(markets) {
  const container = $("searchResults");
  container.innerHTML = "";

  if (!markets || !markets.length) {
    container.textContent = "No markets found.";
    return;
  }

  markets.forEach((m) => {
    const box = document.createElement("div");
    box.className = "search-item";

    const title = document.createElement("div");
    title.className = "search-title";
    title.textContent = m.title;

    const meta = document.createElement("div");
    meta.className = "mono";
    meta.textContent = `market_id=${m.market_id} | liq=${m.liquidity} | opp=${m.opportunity_score}`;

    const question = document.createElement("div");
    question.className = "mono";
    question.textContent = `Q: ${marketQuestionText(m) || "n/a"}`;

    const tok = document.createElement("div");
    tok.className = "mono";
    tok.textContent = `YES=${m.yes_token_id || "N/A"}\nNO=${m.no_token_id || "N/A"}`;

    const map = document.createElement("div");
    map.className = "mono";
    const yesLabel = outcomeLabel(m, "YES") || "question resolves TRUE";
    const noLabel = outcomeLabel(m, "NO") || "question resolves FALSE";
    map.textContent = `YES => ${yesLabel}\nNO => ${noLabel}`;

    const btn = document.createElement("button");
    btn.textContent = "Use This Market";
    btn.onclick = () => {
      selectMarket(m);
    };

    box.append(title, meta, question, tok, map, btn);
    container.appendChild(box);
  });
}

async function handleSearch() {
  try {
    const query = $("searchInput").value.trim();
    if (!query) {
      return;
    }
    const rows = await api(`/api/search?query=${encodeURIComponent(query)}`, { method: "GET" });
    renderSearchResults(rows);
  } catch (err) {
    setText("searchResults", `Search failed: ${err.message}`);
  }
}

async function getTokenMeta(tokenId) {
  const key = String(tokenId || "");
  if (!key) {
    throw new Error("token_id is required.");
  }

  if (state.tokenMetaByTokenId[key]) {
    return state.tokenMetaByTokenId[key];
  }

  const meta = await api(`/api/token/meta?token_id=${encodeURIComponent(key)}`, {
    method: "GET",
  });
  state.tokenMetaByTokenId[key] = meta;
  return meta;
}

function orderDomain(exchangeAddressOverride = null) {
  const ctx = state.me?.trading_context || {};
  return {
    name: "Polymarket CTF Exchange",
    version: "1",
    chainId: Number(ctx.chain_id || 137),
    verifyingContract:
      exchangeAddressOverride ||
      ctx.exchange_address ||
      "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
  };
}

function buildUnsignedOrder({
  tokenId,
  side,
  makerAmount,
  takerAmount,
  feeRateBps = 0,
  nonceOverride,
}) {
  const ctx = state.me.trading_context;
  const sideNum = side === "BUY" ? 0 : 1;
  const signatureType = Number(ctx.signature_type || 0);

  return {
    salt: randomSalt(),
    maker: ctx.trading_address,
    signer: state.me.eoa_address,
    taker: ZERO,
    tokenId: String(tokenId),
    makerAmount: String(makerAmount),
    takerAmount: String(takerAmount),
    expiration: "0",
    nonce: String(nonceOverride ?? Math.floor(Math.random() * 1_000_000_000)),
    feeRateBps: String(feeRateBps),
    side: sideNum,
    signatureType,
  };
}

async function signOrder(unsignedOrder, options = {}) {
  const exchangeAddress = options.exchangeAddress || null;
  const typed = {
    types: ORDER_TYPES,
    primaryType: "Order",
    domain: orderDomain(exchangeAddress),
    message: unsignedOrder,
  };

  const signature = await signTypedDataV4(state.me.eoa_address, typed);

  return {
    salt: String(unsignedOrder.salt),
    maker: unsignedOrder.maker,
    signer: unsignedOrder.signer,
    taker: unsignedOrder.taker,
    tokenId: String(unsignedOrder.tokenId),
    makerAmount: String(unsignedOrder.makerAmount),
    takerAmount: String(unsignedOrder.takerAmount),
    expiration: String(unsignedOrder.expiration),
    nonce: String(unsignedOrder.nonce),
    feeRateBps: String(unsignedOrder.feeRateBps),
    side: unsignedOrder.side === 0 ? "BUY" : "SELL",
    signatureType: Number(unsignedOrder.signatureType),
    signature,
  };
}

function selectedTokenId() {
  const outcome = $("outcome").value;
  if (!state.selectedMarket) {
    throw new Error("Select a market first.");
  }

  const token = outcome === "YES" ? state.selectedMarket.yes_token_id : state.selectedMarket.no_token_id;
  if (!token || token === "None") {
    throw new Error(
      `Selected market has no ${outcome} token id yet. This market is likely not open for trading.`,
    );
  }

  return token;
}

async function handlePlaceEntry() {
  try {
    if (!state.me) {
      throw new Error("Connect and authenticate first.");
    }

    const tokenId = selectedTokenId();
    const price = Number($("price").value);
    const sizeUsdc = Number($("sizeUsdc").value);

    if (!(price > 0 && price < 1)) {
      throw new Error("Price must be in range (0,1)");
    }
    if (!(sizeUsdc > 0)) {
      throw new Error("Size USDC must be > 0");
    }

    const tokenMeta = await getTokenMeta(tokenId);
    const tickSize = String(tokenMeta.tick_size || "0.01");
    const feeRateBps = Number(tokenMeta.fee_rate_bps || 0);
    validatePriceAgainstTick(price, tickSize);

    const requestedSizeTokens = sizeUsdc / price;
    const amounts = computeOrderAmounts({
      side: "BUY",
      sizeTokens: requestedSizeTokens,
      price,
      tickSize,
    });

    const normalizedSizeUsdc = Number(amounts.makerAmount) / 1e6;
    const minOrderSize = toPositiveNumberOrNull(tokenMeta.min_order_size);
    if (minOrderSize !== null && normalizedSizeUsdc + 1e-9 < minOrderSize) {
      throw new Error(
        `Order is below market minimum after rounding. Min is ${minOrderSize} USDC, current maker amount is ${normalizedSizeUsdc.toFixed(6)} USDC. Increase Size USDC.`,
      );
    }
    const unsigned = buildUnsignedOrder({
      tokenId,
      side: "BUY",
      makerAmount: amounts.makerAmount,
      takerAmount: amounts.takerAmount,
      feeRateBps,
    });
    const signedOrder = await signOrder(unsigned, {
      exchangeAddress: tokenMeta.exchange_address,
    });

    const result = await api("/api/order/limit", {
      method: "POST",
      body: JSON.stringify({
        token_id: tokenId,
        side: "BUY",
        outcome: $("outcome").value,
        price: amounts.normalizedPrice,
        size_usdc: normalizedSizeUsdc,
        size_tokens: amounts.normalizedSizeTokens,
        order_type: $("orderType").value,
        idempotency_key: `entry:${Date.now()}`,
        signed_order: signedOrder,
      }),
    });

    state.lastEntry = {
      order_id: result.order_id,
      token_id: tokenId,
      size_tokens: Number(result.entry_size_tokens || amounts.normalizedSizeTokens),
      entry_price: amounts.normalizedPrice,
      exchange_address: tokenMeta.exchange_address,
      neg_risk: Boolean(tokenMeta.neg_risk),
      tick_size: tokenMeta.tick_size,
      fee_rate_bps: feeRateBps,
      signed_order: signedOrder,
    };

    $("entryOrderId").value = result.order_id || "";
    setText(
      "entryState",
      `Entry order submitted: ${result.order_id} | neg_risk=${tokenMeta.neg_risk ? "yes" : "no"} | tick=${tokenMeta.tick_size} | fee=${feeRateBps} | min_size=${tokenMeta.min_order_size || "n/a"}`,
    );
    setJSON("entryBox", result);
  } catch (err) {
    setText("entryState", `Entry failed: ${err.message}`);
  }
}

function readTpLevels() {
  const mode = $("tpMode").value;
  if (mode === "single") {
    return [
      {
        price: Number($("tp1Price").value),
        size_pct: Number($("tp1Pct").value),
      },
    ];
  }

  return [
    { price: Number($("tpL1Price").value), size_pct: Number($("tpL1Pct").value) },
    { price: Number($("tpL2Price").value), size_pct: Number($("tpL2Pct").value) },
    { price: Number($("tpL3Price").value), size_pct: Number($("tpL3Pct").value) },
  ];
}

async function handleArmTp() {
  try {
    if (!state.lastEntry || !state.lastEntry.order_id) {
      throw new Error("Place an entry order first.");
    }

    const levels = readTpLevels();
    const sum = levels.reduce((acc, x) => acc + x.size_pct, 0);
    if (Math.abs(sum - 100) > 0.2) {
      throw new Error("TP percentages must sum to 100");
    }

    const tokenMeta = await getTokenMeta(state.lastEntry.token_id);
    const tickSize = String(tokenMeta.tick_size || state.lastEntry.tick_size || "0.01");
    const feeRateBps = Number(
      tokenMeta.fee_rate_bps ?? state.lastEntry.fee_rate_bps ?? 0,
    );
    const signedTpOrders = [];
    const normalizedLevels = [];
    for (let i = 0; i < levels.length; i += 1) {
      const lv = levels[i];
      validatePriceAgainstTick(Number(lv.price), tickSize);
      const tpTokens = state.lastEntry.size_tokens * (lv.size_pct / 100);
      const amounts = computeOrderAmounts({
        side: "SELL",
        sizeTokens: tpTokens,
        price: Number(lv.price),
        tickSize,
      });
      const unsignedTp = buildUnsignedOrder({
        tokenId: state.lastEntry.token_id,
        side: "SELL",
        makerAmount: amounts.makerAmount,
        takerAmount: amounts.takerAmount,
        feeRateBps,
      });
      const signedTp = await signOrder(unsignedTp, {
        exchangeAddress: tokenMeta.exchange_address,
      });
      normalizedLevels.push({
        price: amounts.normalizedPrice,
        size_pct: Number(lv.size_pct),
      });
      signedTpOrders.push({
        level_index: i,
        order_type: "GTC",
        signed_order: signedTp,
      });
    }

    const body = {
      entry_order_id: state.lastEntry.order_id,
      token_id: state.lastEntry.token_id,
      entry_size_tokens: state.lastEntry.size_tokens,
      mode: $("tpMode").value,
      levels: normalizedLevels,
      signed_tp_orders: signedTpOrders,
    };

    const res = await api("/api/tp/arm", {
      method: "POST",
      body: JSON.stringify(body),
    });

    state.lastArmId = res.arm_id;
    setText("tpState", `TP armed: ${res.arm_id}`);
    setJSON("tpBox", res);
  } catch (err) {
    setText("tpState", `Arm failed: ${err.message}`);
  }
}

async function handleRefreshTp() {
  try {
    const path = state.lastArmId
      ? `/api/tp/status?arm_id=${encodeURIComponent(state.lastArmId)}`
      : "/api/tp/status";
    const res = await api(path, { method: "GET" });
    setJSON("tpBox", res);
  } catch (err) {
    setText("tpState", `Status failed: ${err.message}`);
  }
}

function bindUi() {
  $("btnConnect").addEventListener("click", handleConnect);
  $("btnSearch").addEventListener("click", handleSearch);
  $("btnPlaceEntry").addEventListener("click", handlePlaceEntry);
  $("btnArmTp").addEventListener("click", handleArmTp);
  $("btnRefreshTp").addEventListener("click", handleRefreshTp);
  $("outcome").addEventListener("change", updateMarketUiState);

  $("tpMode").addEventListener("change", () => {
    const mode = $("tpMode").value;
    $("tpSingle").classList.toggle("hidden", mode !== "single");
    $("tpLadder").classList.toggle("hidden", mode !== "ladder");
  });

  updateMarketUiState();
}

bindUi();
