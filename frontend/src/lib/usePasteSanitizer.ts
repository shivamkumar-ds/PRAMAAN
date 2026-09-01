import { useEffect } from "react";

/**
 * Global fix for "pasting leaves a leading/trailing space in the field" --
 * reported across the app (Capabilities manual-add form, but the same
 * clipboard content shows up anywhere a user pastes text copied out of a
 * tender PDF, which very commonly carries leading whitespace from list
 * indentation). Wired ONCE at the app root (App.tsx) rather than patched
 * into every input, so it covers both the shared kit Input/Textarea
 * (components/kit/Form.tsx) and every raw <input>/<textarea> elsewhere
 * (Combobox, SearchInput, Dropzone, TenderUpload, ContactSection,
 * Evaluation.tsx) without touching any of those files individually.
 *
 * Only trims text/textarea-type fields -- never touches paste into
 * date/file/checkbox/radio inputs, and never touches typing, only an
 * actual paste event. If the clipboard text has no leading/trailing
 * whitespace to strip, the native paste is left completely alone (no
 * behavior change, no re-render) rather than always intercepting.
 */
const TEXT_INPUT_TYPES = new Set([
  "text", "search", "email", "tel", "url", "password", "number",
]);

function isSanitizableTarget(target: EventTarget | null): target is HTMLInputElement | HTMLTextAreaElement {
  if (target instanceof HTMLTextAreaElement) return true;
  if (target instanceof HTMLInputElement) return TEXT_INPUT_TYPES.has(target.type);
  return false;
}

// Manually writing target.value and dispatching a plain "input" event
// wouldn't be seen by React's controlled inputs (React tracks value via
// its own value-setter interception). This is the standard workaround:
// call the *native* HTMLInputElement/HTMLTextAreaElement value setter
// (bypassing React's overridden one) so React's change-detection sees a
// real mutation, then dispatch a bubbling "input" event so the
// component's onChange fires normally with the corrected value -- works
// identically for controlled and uncontrolled fields.
function setNativeValue(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  descriptor?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

export function usePasteSanitizer() {
  useEffect(() => {
    function handlePaste(e: ClipboardEvent) {
      const target = e.target;
      if (!isSanitizableTarget(target)) return;

      const pasted = e.clipboardData?.getData("text");
      if (pasted == null) return;
      const trimmed = pasted.trim();
      if (trimmed === pasted) return; // nothing to fix -- let the native paste happen untouched

      e.preventDefault();
      const start = target.selectionStart ?? target.value.length;
      const end = target.selectionEnd ?? target.value.length;
      const nextValue = target.value.slice(0, start) + trimmed + target.value.slice(end);
      setNativeValue(target, nextValue);
      const caret = start + trimmed.length;
      target.setSelectionRange(caret, caret);
    }

    // Capture phase, document-wide -- catches every input/textarea in the
    // app regardless of which component rendered it, present or future.
    document.addEventListener("paste", handlePaste, true);
    return () => document.removeEventListener("paste", handlePaste, true);
  }, []);
}
