/* Hand-written animation runtime for chapter figures. No dependencies.
   Motion is an enhancement: the SVG is rendered in its static state, controls
   appear only after this script mounts, and reduced-motion users start paused. */
(function () {
  "use strict";

  function init(fig) {
    var script = fig.querySelector("script.fig-anim");
    if (!script) return;

    var spec;
    try {
      spec = JSON.parse(script.textContent);
    } catch (e) {
      return;
    }
    var steps = spec.steps || [];
    if (!steps.length) return;

    var parts = Array.prototype.slice.call(fig.querySelectorAll("[data-part]"));
    var label = fig.querySelector(".fig-label");
    var index = -1;
    var timer = null;
    var intro = spec.intro || "Press Play or Next to trace the figure.";

    function render() {
      if (index < 0) {
        parts.forEach(function (part) {
          part.classList.remove("is-active", "is-dim");
        });
        if (label) label.textContent = intro;
        return;
      }
      var step = steps[index];
      var active = step.highlight || step.active || [];
      parts.forEach(function (part) {
        var names = (part.getAttribute("data-part") || "").split(/\s+/);
        var on = names.some(function (name) {
          return active.indexOf(name) !== -1;
        });
        part.classList.toggle("is-active", on);
        part.classList.toggle("is-dim", !on);
      });
      if (label) label.textContent = step.label || "";
    }

    function stop() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    function play() {
      if (timer) return;
      if (index === steps.length - 1) index = -1;
      timer = setInterval(function () {
        if (index >= steps.length - 1) {
          stop();
          return;
        }
        index += 1;
        render();
      }, spec.interval || 1400);
      if (index < 0) {
        index = 0;
        render();
      }
    }

    function next() {
      stop();
      if (index < steps.length - 1) {
        index += 1;
        render();
      }
    }

    function prev() {
      stop();
      if (index > -1) {
        index -= 1;
        render();
      }
    }

    function reset() {
      stop();
      index = -1;
      render();
    }

    var bindings = [
      ["[data-play]", play],
      ["[data-pause]", stop],
      ["[data-prev]", prev],
      ["[data-next]", next],
      ["[data-reset]", reset]
    ];
    bindings.forEach(function (pair) {
      var button = fig.querySelector(pair[0]);
      if (button) button.addEventListener("click", pair[1]);
    });

    fig.addEventListener("keydown", function (event) {
      if (event.target && event.target.tagName === "BUTTON") return;
      if (event.key === "ArrowRight") {
        event.preventDefault();
        event.stopPropagation();
        next();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        event.stopPropagation();
        prev();
      } else if (event.key === " ") {
        event.preventDefault();
        event.stopPropagation();
        if (timer) stop();
        else play();
      }
    });

    fig.classList.add("is-animated");
    render();

    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) stop();
        });
      }, { threshold: 0.25 });
      observer.observe(fig);
    }

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
    });
  }

  function initAll() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".chapter-figure[data-fig-id]"),
      init
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
