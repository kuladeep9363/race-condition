document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".flash").forEach((item) => {
    window.setTimeout(() => {
      item.classList.add("flash-fade");
      window.setTimeout(() => item.remove(), 350);
    }, 5000);
  });
});
