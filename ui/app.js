const state = {
  address: null,
  me: null,
  selectedMarket: null,
  lastEntry: null,
  lastArmId: null,
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

const $ = (id) => document.getElementById(id);

function setText(id, text) {
  $(id).textContent = text;
}

function setJSON(id, value) {
  $(id).textContent = JSON.stringify(value, null, 2);
}

function toMicro(amount) {
  const n = Number(amount);
  if (!Number.isFinite(n) || n <= 0) {
    throw new Error(`Invalid amount: ${amount}`);
  }
  return BigInt(Math.round(n * 1e6));
}

function randomUint(bits = 256) {
  const bytes = Math.ceil(bits / 8);
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  const hex = Array.from(arr)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return BigInt(`0x${hex}`).toString();
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
  const data = text ? JSON.parse(text) : {};

  if (!resp.ok) {
    throw new Error(data.detail || `HTTP ${resp.status}`);
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

async function signPersonal(address, message) {
  return window.ethereum.request({
    method: "personal_sign",
    params: [message, address],
  });
}

async function signTypedDataV4(address, typedData) {
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

    const tok = document.createElement("div");
    tok.className = "mono";
    tok.textContent = `YES=${m.yes_token_id || "N/A"}\nNO=${m.no_token_id || "N/A"}`;

    const btn = document.createElement("button");
    btn.textContent = "Use This Market";
    btn.onclick = () => {
      state.selectedMarket = m;
      $("marketId").value = m.market_id || "";
      $("marketTitle").value = m.title || "";
      $("yesToken").value = m.yes_token_id || "";
      $("noToken").value = m.no_token_id || "";
    };

    box.append(title, meta, tok, btn);
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

function orderDomain() {
  const ctx = state.me?.trading_context || {};
  return {
    name: "Polymarket CTF Exchange",
    version: "1",
    chainId: Number(ctx.chain_id || 137),
    verifyingContract: ctx.exchange_address || "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
  };
}

function buildUnsignedOrder({ tokenId, side, price, sizeTokens, nonceOverride }) {
  const ctx = state.me.trading_context;
  const sideNum = side === "BUY" ? 0 : 1;
  const signatureType = Number(ctx.signature_type || 0);

  const makerAmount =
    side === "BUY"
      ? toMicro(sizeTokens * price).toString()
      : toMicro(sizeTokens).toString();

  const takerAmount =
    side === "BUY"
      ? toMicro(sizeTokens).toString()
      : toMicro(sizeTokens * price).toString();

  return {
    salt: randomUint(256),
    maker: ctx.trading_address,
    signer: state.me.eoa_address,
    taker: ZERO,
    tokenId: String(tokenId),
    makerAmount,
    takerAmount,
    expiration: "0",
    nonce: String(nonceOverride ?? Math.floor(Math.random() * 1_000_000_000)),
    feeRateBps: "0",
    side: sideNum,
    signatureType,
  };
}

async function signOrder(unsignedOrder) {
  const typed = {
    types: ORDER_TYPES,
    primaryType: "Order",
    domain: orderDomain(),
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
    throw new Error(`Selected market has no ${outcome} token id.`);
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

    const sizeTokens = sizeUsdc / price;
    const unsigned = buildUnsignedOrder({
      tokenId,
      side: "BUY",
      price,
      sizeTokens,
    });
    const signedOrder = await signOrder(unsigned);

    const result = await api("/api/order/limit", {
      method: "POST",
      body: JSON.stringify({
        token_id: tokenId,
        side: "BUY",
        outcome: $("outcome").value,
        price,
        size_usdc: sizeUsdc,
        size_tokens: sizeTokens,
        order_type: $("orderType").value,
        idempotency_key: `entry:${Date.now()}`,
        signed_order: signedOrder,
      }),
    });

    state.lastEntry = {
      order_id: result.order_id,
      token_id: tokenId,
      size_tokens: Number(result.entry_size_tokens || sizeTokens),
      entry_price: price,
      signed_order: signedOrder,
    };

    $("entryOrderId").value = result.order_id || "";
    setText("entryState", `Entry order submitted: ${result.order_id}`);
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

    const signedTpOrders = [];
    for (let i = 0; i < levels.length; i += 1) {
      const lv = levels[i];
      const tpTokens = state.lastEntry.size_tokens * (lv.size_pct / 100);
      const unsignedTp = buildUnsignedOrder({
        tokenId: state.lastEntry.token_id,
        side: "SELL",
        price: lv.price,
        sizeTokens: tpTokens,
      });
      const signedTp = await signOrder(unsignedTp);
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
      levels,
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

  $("tpMode").addEventListener("change", () => {
    const mode = $("tpMode").value;
    $("tpSingle").classList.toggle("hidden", mode !== "single");
    $("tpLadder").classList.toggle("hidden", mode !== "ladder");
  });
}

bindUi();
