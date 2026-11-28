const metrics = [
  ["oldestPendingJobAgeSeconds", "Tuổi job lâu nhất", "giây"],
  ["pendingJobs", "Job đang chờ hoặc đang xử lý", ""],
  ["p95LatencySeconds", "Độ trễ xử lý p95 trong 1 giờ", "giây"],
  ["failureRate", "Tỷ lệ lỗi trong 1 giờ", "%"],
  ["totalRetries", "Tổng số lần thử lại", ""],
  ["thumbnailBytes", "Dung lượng thumbnail đã ghi nhận", "byte"],
  ["completedWithoutThumbnailSize", "Ảnh hoàn tất thiếu số liệu dung lượng", ""]
];
const form = document.querySelector("#connect");
const status = document.querySelector("#status");
const rows = document.querySelector("#metrics");
const format = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2 });
let timer;
let run = 0;

form.addEventListener("submit", event => {
  event.preventDefault();
  clearTimeout(timer);
  const token = form.elements.token.value;
  form.reset();
  const currentRun = ++run;

  async function refresh() {
    try {
      const response = await fetch("/api/metrics", {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
        redirect: "error", signal: AbortSignal.timeout(12000)
      });
      if (!response.ok) throw new Error("Không lấy được số liệu giám sát.");
      const result = await response.json();
      if (currentRun !== run) return;
      rows.replaceChildren(...metrics.map(([key, label, unit]) => {
        const row = document.createElement("tr");
        row.insertCell().textContent = label;
        const value = result[key];
        row.insertCell().textContent = value == null ? "—" :
          `${format.format(unit === "%" ? value * 100 : value)} ${unit}`.trim();
        return row;
      }));
      status.textContent = `Cập nhật: ${new Date(result.sampledAt).toLocaleString("vi-VN")}`;
      timer = setTimeout(refresh, 15000);
    } catch {
      if (currentRun !== run) return;
      rows.replaceChildren();
      status.textContent = "Không lấy được số liệu. Kiểm tra token và trạng thái API rồi kết nối lại.";
    }
  }

  refresh();
});
