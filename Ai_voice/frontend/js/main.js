/**
 * Nova OS Main Entry Point
 * Clock, system telemetry, and initial window lifecycle.
 */

// Update system clock
function updateClock() {
    const now = new Date();
    const hours = now.getHours().toString().padStart(2, '0');
    const minutes = now.getMinutes().toString().padStart(2, '0');
    const timeEl = document.getElementById('sys-time');
    if (timeEl) timeEl.textContent = `${hours}:${minutes}`;

    const year = now.getFullYear();
    const month = (now.getMonth() + 1).toString().padStart(2, '0');
    const day = now.getDate().toString().padStart(2, '0');
    const dateEl = document.getElementById('sys-date');
    if (dateEl) dateEl.textContent = `${year}-${month}-${day}`;
}

// Simulate realistic system CPU telemetry
function updateCpu() {
    const cpuEl = document.getElementById('sys-cpu');
    if (!cpuEl) return;
    const base = 8;
    const fluctuation = Math.floor(Math.random() * 9);
    cpuEl.textContent = `CPU ${base + fluctuation}%`;
}


setInterval(updateClock, 1000);
setInterval(updateCpu, 3000);
updateClock();
updateCpu();

// App initialization
window.addEventListener('DOMContentLoaded', () => {
    // Open Nova Voice by default on boot
    setTimeout(() => {
        if (window.WindowManager) {
            window.WindowManager.openApp('nova-voice');
        }
    }, 400);
});
