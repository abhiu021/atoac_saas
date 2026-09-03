// Product Detail Page
const requireRole = (role) => {
  try {
    const token = localStorage.getItem("token");
    if (!token) {
      window.location.href = "/login.html";
      return null;
    }
    const decoded = JSON.parse(atob(token.split(".")[1]));
    if (decoded.role !== role) {
      window.location.href = "/login.html";
      return null;
    }
    return decoded;
  } catch {
    window.location.href = "/login.html";
    return null;
  }
};

const user = requireRole("buyer");
const $ = (id) => document.getElementById(id);
const inr = (n) => n == null ? "—" : "₹" + Number(n).toLocaleString("en-IN");
const esc = (s) => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Product icon mapping (improved without emojis)
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

// Get product ID from URL
const urlParams = new URLSearchParams(window.location.search);
const productId = urlParams.get("id");
const candidateData = urlParams.get("data"); // Optional: full candidate data passed via URL

async function loadProductDetails() {
  if (!productId) {
    $("pageTitle").textContent = "Product Not Found";
    return;
  }

  try {
    // If we have candidate data from URL, use it directly
    let product;
    if (candidateData) {
      try {
        product = JSON.parse(decodeURIComponent(candidateData));
      } catch {
        product = null;
      }
    }

    // Otherwise fetch from API
    if (!product) {
      // Note: This assumes your backend has an endpoint to fetch product details
      // Adjust the endpoint based on your actual API structure
      const response = await api(`/api/products/${productId}`);
      product = response;
    }

    renderProductDetails(product);
  } catch (error) {
    console.error("Error loading product:", error);
    toast("Could not load product details.", "err");
  }
}

function renderProductDetails(product) {
  // Basic Info
  $("productName").textContent = esc(product.name || "Unnamed Product");
  $("merchantName").textContent = esc(product.merchant_name || "Unknown Merchant");
  $("productDesc").textContent = product.description || "";

  // Image
  const imageContainer = $("productImage");
  if (product.image_url) {
    imageContainer.innerHTML = `<img src="${product.image_url}" alt="${esc(product.name)}" style="width: 100%; height: 100%; object-fit: cover; border-radius: var(--radius);">`;
  } else {
    const icon = getProductIcon(product.name);
    const tint = getTintColor(product.name);
    imageContainer.style.background = tint;
    imageContainer.textContent = icon;
  }

  // Pricing
  $("listPrice").textContent = inr(product.list_price);
  $("moq").textContent = (product.min_order_qty || 0) + " units";
  $("stock").textContent = product.stock != null ? product.stock + " units available" : "Check with seller";
  $("delivery").textContent = (product.delivery_days || "—") + " days";

  // Specs
  $("category").textContent = product.category || "General";
  $("productId").textContent = productId || product.id || "—";

  // Descriptions
  $("fullDescription").textContent = product.description || 
    "This is a quality product available from a verified ATOAC merchant. Contact the seller for more specifications and customization options.";
  
  $("merchantBusinessName").textContent = esc(product.merchant_name || "Merchant");
  $("merchantEmail").textContent = product.merchant_email || "Available on ATOAC";

  // Make merchant section clickable
  const merchantSection = $("merchantSection");
  if (merchantSection && product.merchant_id) {
    merchantSection.onclick = () => viewMerchantProfile(product.merchant_id);
    merchantSection.style.cursor = "pointer";
  }
}

function toast(msg, cls = "") {
  const el = document.createElement("div");
  el.className = "toast " + cls;
  el.textContent = msg;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

window.negotiateNow = () => {
  // Store product in session and redirect to buyer chat
  sessionStorage.setItem("selectedProduct", JSON.stringify({
    id: productId,
    name: $("productName").textContent,
    merchant: $("merchantName").textContent
  }));
  window.location.href = "/buyer.html";
};

window.contactMerchant = () => {
  toast("Opening merchant contact... (Implement contact form)", "ok");
  // Implement actual contact functionality
};

window.viewMerchantProfile = (merchantId) => {
  if (merchantId) {
    window.location.href = `/merchant-detail.html?id=${encodeURIComponent(merchantId)}`;
  } else {
    const merchantName = $("merchantName").textContent;
    // Fallback: redirect with merchant name if no ID
    window.location.href = `/merchant-detail.html?name=${encodeURIComponent(merchantName)}`;
  }
};

// Helper function for API calls
async function api(path, opts = {}) {
  const token = localStorage.getItem("token");
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
document.addEventListener("DOMContentLoaded", loadProductDetails);
