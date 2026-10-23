(() => {
  "use strict";
  const composing = new WeakSet();
  const pendingFormats = new WeakMap();
  const liveDisplays = new WeakMap();
  const liveTexts = new WeakMap();
  const bound = new WeakSet();
  const handledEvents = new WeakSet();
  const selector = ".acc-diamond, .acc-paypal, [data-grouped-integer]";

  function showLiveComposition(input, options) {
    let display = liveDisplays.get(input);
    if (!display) {
      display = document.createElement("span");
      display.className = "deposit-amount-live";
      display.setAttribute("aria-hidden", "true");
      input.insertAdjacentElement("afterend", display);
      liveDisplays.set(input, display);
    }
    const raw = input.value;
    const digits = raw.replace(/\D/g, "");
    const text = liveTexts.get(input) || "";
    const valid = /^[\d.]+$/.test(raw) && !(text.includes(".") && !/^(?:\d+|\d{1,3}(?:\.\d{3})+)$/.test(text));
    const maximum = typeof options.maximum === "function" ? options.maximum() : options.maximum;
    const visibleDigits = valid && Number.isSafeInteger(maximum) && Number(digits) > maximum ? String(maximum) : digits;
    const formatted = valid ? visibleDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ".") : raw;
    const position = offset => {
      if (!valid) return offset;
      const count = raw.slice(0, offset).replace(/\D/g, "").length;
      if (!count) return 0;
      let seen = 0;
      for (let i = 0; i < formatted.length; i++) {
        if (formatted[i] !== "." && ++seen === count) return i + 1;
      }
      return formatted.length;
    };
    const start = position(input.selectionStart), end = position(input.selectionEnd);
    const selection = document.createElement("span");
    selection.className = "deposit-amount-live-selection";
    selection.textContent = formatted.slice(start, end);
    const caret = document.createElement("i");
    caret.className = "deposit-amount-live-caret";
    display.replaceChildren(document.createTextNode(formatted.slice(0, start)), selection, caret, document.createTextNode(formatted.slice(end)));
    display.hidden = false;
    input.classList.add("has-live-composition");
  }

  function hideLiveComposition(input) {
    const display = liveDisplays.get(input);
    if (display) display.hidden = true;
    input.classList.remove("has-live-composition");
  }

  function normalize(event, options = {}) {
    const input = event.target;
    // Changing value/selection during composition invalidates the IME's native
    // replacement range. Leave the entire edit to the browser until it commits.
    if (event.isComposing || composing.has(input)) {
      if (options.liveComposition) {
        if (typeof event.data === "string") liveTexts.set(input, event.data);
        showLiveComposition(input, options);
      }
      return;
    }
    hideLiveComposition(input);
    cancelAnimationFrame(pendingFormats.get(input));
    pendingFormats.delete(input);
    const commit = ["change", "blur", "focusout"].includes(event.type);
    if (input.value === "" && (input.hasAttribute("data-empty-zero") || (commit && options.minimum !== undefined))) {
      input.value = input.hasAttribute("data-empty-zero") ? "0" : String(options.minimum);
      input.setSelectionRange(0, input.value.length);
      return;
    }
    if (options.rejectMalformed !== false && !/^[\d.]+$/.test(input.value)) return;
    const validGroups = /^(?:\d+|\d{1,3}(?:\.\d{3})+)$/;
    if (options.rejectMalformed !== false) {
      if (event.type !== "input" && !validGroups.test(input.value)) return;
      if (event.data?.includes(".") && !validGroups.test(event.data)) return;
      if (event.inputType === "insertFromPaste" && !validGroups.test(input.value)) return;
    }
    const raw = input.value;
    const digits = raw.replace(/\D/g, "");
    if (!digits) return;
    let trimmed = digits.replace(/^0+(?=\d)/, "");
    const maximum = typeof options.maximum === "function" ? options.maximum() : options.maximum;
    if (Number.isSafeInteger(maximum) && Number(trimmed) > maximum) trimmed = String(maximum);
    if (commit && options.minimum !== undefined && Number(trimmed) < options.minimum) trimmed = String(options.minimum);
    const normalized = trimmed.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    if (normalized === input.value) return;
    const removed = digits.length - trimmed.length;
    const caretPosition = position => {
      const count = Math.max(0, raw.slice(0, position).replace(/\D/g, "").length - removed);
      if (!count) return 0;
      let seen = 0;
      for (let index = 0; index < normalized.length; index++) {
        if (normalized[index] !== "." && ++seen === count) {
          const afterSeparator = raw[position - 1] === "." || event.inputType === "deleteContentForward";
          return index + 1 + (afterSeparator && normalized[index + 1] === "." ? 1 : 0);
        }
      }
      return normalized.length;
    };
    const start = caretPosition(input.selectionStart), end = caretPosition(input.selectionEnd);
    input.value = normalized;
    input.setSelectionRange(start, end);
  }

  function bind(container, options = {}) {
    if (!container || bound.has(container)) return;
    bound.add(container);
    const matches = input => input instanceof HTMLInputElement && (container === input || input.matches(options.selector || selector));
    container.addEventListener("compositionstart", event => {
      const input = event.target;
      if (!matches(input)) return;
      cancelAnimationFrame(pendingFormats.get(input));
      pendingFormats.delete(input);
      composing.add(input);
      liveTexts.delete(input);
      if (options.liveComposition) showLiveComposition(input, options);
    });
    if (options.liveComposition) container.addEventListener("select", event => {
      if (matches(event.target) && composing.has(event.target)) showLiveComposition(event.target, options);
    });
    container.addEventListener("compositionend", event => {
      const input = event.target;
      if (!matches(input) || handledEvents.has(event)) return;
      handledEvents.add(event);
      composing.delete(input);
      // Some IMEs emit their final input after compositionend. Let that native
      // commit finish before formatting; a subsequent input cancels this frame.
      pendingFormats.set(input, requestAnimationFrame(() => normalize({ target: input, type: "input", data: event.data }, options)));
    });
    for (const type of ["input", "change", "focusout"]) {
      container.addEventListener(type, event => {
        if (!matches(event.target) || handledEvents.has(event)) return;
        handledEvents.add(event);
        normalize(event, options);
      });
    }
  }

  window.VietlottNumericInput = Object.freeze({ bind, normalize });
})();
