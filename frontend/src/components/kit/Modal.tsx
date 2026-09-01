import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "../../lib/cn";

/**
 * Generic content modal -- ConfirmDialog already covers "confirm a single
 * destructive/simple action"; this is for anything that needs a real form
 * or richer body (a create-procurement form, a multi-field bidder form,
 * etc.) with its own footer actions. Same portal-to-document.body
 * reasoning as ConfirmDialog (Layout's sticky header would otherwise
 * paint over a non-portaled overlay -- see that component's comment).
 */
export function Modal({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  size = "md",
}: {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  onClose: () => void;
  size?: "sm" | "md" | "lg";
}) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const widths = { sm: "max-w-sm", md: "max-w-md", lg: "max-w-lg" };

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/25 animate-fade-in overflow-y-auto"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        onClick={(e) => e.stopPropagation()}
        className={cn("w-full rounded-lg border border-border bg-surface shadow-hero my-8", widths[size])}
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-5 pb-1">
          <div>
            <h2 id="modal-title" className="text-sm font-semibold tracking-tight">
              {title}
            </h2>
            {description && <p className="text-xs text-muted-foreground mt-1">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-muted-foreground hover:text-foreground transition shrink-0"
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2.5 px-5 pb-5 pt-2">{footer}</div>}
      </div>
    </div>,
    document.body
  );
}
