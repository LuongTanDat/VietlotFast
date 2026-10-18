(() => {
  "use strict";
  const compositions = new WeakMap();
  const bound = new WeakSet();
  const handledEvents = new WeakSet();
  const selector = ".acc-diamond, .acc-paypal, [data-grouped-integer]";

  function normalize(event, options = {}) {
    const input = event.target;
    const composition = compositions.get(input);
    const composingNumber = event.isComposing && typeof event.data === "string" && /^[\d.]*$/.test(event.data);
    const finalComposition = !event.isComposing && event.type === "input" && composition &&
      ["insertText", "insertCompositionText", "insertFromComposition"].includes(event.inputType) && event.data === composition.text;
    if (composition && (composingNumber || finalComposition)) {
      // IMEs send the whole replacement text, not just the newest digit. A
      // separator rewrite may reset Chrome's native range, so retain our own.
      input.value = composition.prefix + event.data + composition.suffix;
      const caret = composition.prefix.length + event.data.length;
      input.setSelectionRange(caret, caret);
      composition.text = event.data;
    }
    if (!event.isComposing) compositions.delete(input);
    const commit = ["change", "blur", "focusout"].includes(event.type);
    if (input.value === "" && (input.hasAttribute("data-empty-zero") || (commit && options.minimum !== undefined))) {
      input.value = input.hasAttribute("data-empty-zero") ? "0" : String(options.minimum);
      input.setSelectionRange(0, input.value.length);
      if (composingNumber && composition) {
        composition.rendered = input.value;
        composition.caret = 0;
      }
      return;
    }
    if (options.rejectMalformed !== false && !/^[\d.]+$/.test(input.value)) return;
    const rememberComposition = () => {
      if (composingNumber && composition) {
        composition.rendered = input.value;
        composition.caret = input.selectionStart;
      }
    };
    const validGroups = /^(?:\d+|\d{1,3}(?:\.\d{3})+)$/;
    if (options.rejectMalformed !== false) {
      if (event.type !== "input" && !validGroups.test(input.value)) return;
      if (!composingNumber && !finalComposition && event.data?.includes(".") && !validGroups.test(event.data)) return;
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
    if (normalized === input.value) { rememberComposition(); return; }
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
    rememberComposition();
  }

  function bind(container, options = {}) {
    if (!container || bound.has(container)) return;
    bound.add(container);
    const matches = input => input instanceof HTMLInputElement && (container === input || input.matches(options.selector || selector));
    container.addEventListener("compositionstart", event => {
      const input = event.target;
      if (!matches(input)) return;
      const previous = compositions.get(input);
      if (previous && input.value === previous.rendered && input.selectionStart === previous.caret && input.selectionEnd === previous.caret) return;
      compositions.set(input, { prefix: input.value.slice(0, input.selectionStart), suffix: input.value.slice(input.selectionEnd), text: null, rendered: input.value, caret: input.selectionStart });
    });
    container.addEventListener("keydown", event => {
      if (!event.isComposing && event.key !== "Process") compositions.delete(event.target);
    });
    container.addEventListener("pointerdown", event => compositions.delete(event.target));
    for (const type of ["input", "compositionend", "change", "focusout"]) {
      container.addEventListener(type, event => {
        if (!matches(event.target) || handledEvents.has(event)) return;
        handledEvents.add(event);
        normalize(event, options);
      });
    }
  }

  window.VietlottNumericInput = Object.freeze({ bind, normalize });
})();
