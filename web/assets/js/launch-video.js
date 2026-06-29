(function () {
  "use strict";

  const frame = document.getElementById("launch-video-frame");
  const video = document.getElementById("launch-video");
  const playBtn = document.getElementById("launch-video-play");
  const unmuteWrap = document.getElementById("launch-video-unmute");
  const soundBtn = document.getElementById("launch-video-sound");

  if (!frame || !video || !playBtn) return;

  function showPlaying() {
    frame.classList.add("is-playing");
    playBtn.hidden = true;
  }

  function showPaused() {
    frame.classList.remove("is-playing");
    playBtn.hidden = false;
  }

  playBtn.addEventListener("click", () => {
    video.muted = false;
    video.play().then(showPlaying).catch(() => {
      video.muted = true;
      video.play().then(() => {
        showPlaying();
        if (unmuteWrap) unmuteWrap.hidden = false;
      });
    });
  });

  soundBtn?.addEventListener("click", () => {
    video.muted = false;
    video.volume = 1;
    if (unmuteWrap) unmuteWrap.hidden = true;
  });

  video.addEventListener("ended", showPaused);
  video.addEventListener("pause", () => {
    if (video.currentTime > 0 && !video.ended) return;
    showPaused();
  });

  video.addEventListener("click", () => {
    if (video.paused) {
      playBtn.click();
    } else {
      video.pause();
      showPaused();
    }
  });
})();
