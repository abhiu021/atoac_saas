// Merchant Detail Page
const user = requireRole("buyer");
const $ = (id) => document.getElementById(id);
const inr = (n) => n == null ? "—" : "₹" + Number(n).toLocaleString("en-IN");
const esc = (s) => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Product icon mapping
const PRODUCT_ICONS = {
  chair: "🪑", desk: "🖥️", table: "🖥️", lamp: "💡", monitor: "🖥️",
  cable: "🔌", bottle: "🍶", pipe: "🧵", paper: "📋", pen: "✏️",
  bag: "👜", shoe: "👞", phone: "📱", box: "📦", keyboard: "⌨️"
};

function getProductIcon(name) {
  const lower = (name || "").toLowerCase();
  for (const [key, icon] of Object.entries(PRODUCT_ICONS)) {
    if (lower.includes(key)) return icon;
  }
  return "📦";
}

const TINTS = ["#fff0e2", "#eef4ff", "#eafaf1", "#fdf0f4", "#f3f0ff", "#fff7e6"];
function getTintColor(name) {
  let h = 0;
  for (const ch of name || "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TINTS[h % TINTS.length];
}

// Get merchant ID from URL
const urlParams = new URLSearchParams(window.location.search);
const merchantId = urlParams.get("id");
const merchantName = urlParams.get("name");
const merchantData = urlParams.get("data"); // Optional: full merchant data passed via URL

let merchant = null;
let merchantProducts = [];

async function loadMerchantDetails() {
  try {
    // If we have merchant data from URL, use it directly
    if (merchantData) {
      try {
        merchant = JSON.parse(decodeURIComponent(merchantData));
      } catch {
        merchant = null;
      }
    }

    // Otherwise fetch from API
    if (!merchant) {
      if (merchantId) {
        const response = await api(`/api/merchants/${merchantId}`);
        merchant = response;
      } else if (merchantName) {
        const response = await api(`/api/merchants/search?name=${encodeURIComponent(merchantName)}`);
        merchant = response[0] || null;
      }
    }

    if (!merchant) {
      throw new Error("Merchant not found");
    }

    renderMerchantDetails(merchant);
    await loadMerchantProducts(merchant.id || merchantId);
  } catch (error) {
    console.error("Error loading merchant:", error);
    toast("Could not load merchant details.", "err");
  }
}

function renderMerchantDetails(m) {
  // Basic Info
  $("merchantName").textContent = esc(m.business_name || m.name || "Unknown Merchant");
  $("merchantEmail").textContent = esc(m.email || "contact@merchant.com");
  $("merchantAvatar").textContent = (m.business_name || m.email || "M")[0].toUpperCase();

  // Stats
  $("productCount").textContent = m.product_count || "—";
  $("dealCount").textContent = m.deal_count || "0";
  $("avgDelivery").textContent = (m.avg_delivery_days || "—") + " days";
  $("completionRate").textContent = (m.completion_rate || "—") + "%";

  // Description
  $("merchantDescription").textContent = m.description || 
    "Professional merchant on ATOAC providing quality products with verified credentials and reliable delivery.";

  // Contact Info
  $("contactEmail").textContent = esc(m.email || "contact@merchant.com");
  $("deliveryInfo").textContent = (m.avg_delivery_days || "—") + " days";
}

async function loadMerchantProducts(mId) {
  try {
    // Try to fetch merchant's products
    const response = await api(`/api/merchants/${mId}/products`);
    merchantProducts = response || [];
    renderProducts();
  } catch (error) {
    console.error("Error loading products:", error);
    // If API endpoint doesn't exist, show placeholder
    $("productsGrid").innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--muted); grid-column: 1 / -1;">
        Products will be listed here once the API is available.
      </div>
    `;
  }
}

function renderProducts() {
  const grid = $("productsGrid");
  if (!merchantProducts.length) {
    grid.innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--muted); grid-column: 1 / -1;">
        No products listed yet. Check back soon!
      </div>
    `;
    return;
  }

  grid.innerHTML = merchantProducts.map(p => {
    const imageHtml = p.image_url 
      ? `<img src="${p.image_url}" alt="" data-product-name="${esc(p.name)}" onerror="this.onerror=null;this.style.display='none';this.parentElement.classList.add('image-missing');this.parentElement.textContent=getProductIcon(this.dataset.productName);" style="width: 100%; height: 100%; object-fit: cover;">`
      : `<div style="width: 100%; height: 100%; background: ${getTintColor(p.name)}; display: flex; align-items: center; justify-content: center; font-size: 24px;">${getProductIcon(p.name)}</div>`;
    return `
      <div class="product-item" onclick="viewProductDetail('${p.id || p.product_id}', '${esc(p.name)}')">
        <div class="img">${imageHtml}</div>
        <div class="name">${esc(p.name)}</div>
        <div class="price">${inr(p.list_price)}</div>
      </div>
    `;
  }).join("");
}

function toast(msg, cls = "") {
  const el = document.createElement("div");
  el.className = "toast " + cls;
  el.textContent = msg;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

window.negotiateWithMerchant = () => {
  if (!merchant) return toast("Merchant info not loaded.", "err");
  sessionStorage.setItem("selectedMerchant", JSON.stringify({
    id: merchant.id || merchantId,
    name: merchant.business_name || merchant.name
  }));
  window.location.href = "/buyer.html";
};

window.contactMerchant = () => {
  toast("Opening contact form...", "ok");
  // Implement actual contact functionality
};

window.viewProductDetail = (prodId, prodName) => {
  window.location.href = `/product-detail.html?id=${encodeURIComponent(prodId)}&name=${encodeURIComponent(prodName)}`;
};

// Helper function for API calls
async function api(path, opts = {}) {
  const token = localStorage.getItem("atoac_token");
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token && { Authorization: `Bearer ${token}` }),
      ...opts.headers,
    },
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// Load on page ready
document.addEventListener("DOMContentLoaded", loadMerchantDetails);
