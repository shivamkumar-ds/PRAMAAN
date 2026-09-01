import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "warning";
type Size = "sm" | "md" | "lg";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: React.ReactNode;
}

const variants: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground hover:bg-primary-hover shadow-xs",
  secondary: "bg-accent text-accent-foreground hover:opacity-90",
  outline: "border border-border bg-surface text-foreground hover:bg-surface-hover",
  ghost: "text-foreground hover:bg-surface-hover",
  danger: "bg-danger text-danger-foreground hover:opacity-90",
  // Same soft/border pattern as Badge.tsx's "warning" tone, promoted into
  // an actual button variant -- for actions that are a real decision
  // (worth standing out from a plain outline button) but not as
  // consequential/destructive as danger.
  warning: "bg-warning-soft text-warning border border-warning/30 hover:bg-warning/20",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-11 px-6 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ className, variant = "primary", size = "md", loading, icon, children, disabled, ...props }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center rounded-md font-medium transition-colors duration-150",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          variants[variant],
          sizes[size],
          className
        )}
        {...props}
      >
        {loading ? <Loader2 size={15} className="animate-spin" /> : icon}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";
