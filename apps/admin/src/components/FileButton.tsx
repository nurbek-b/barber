import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { buttonVariants } from "@/components/ui";
import { cn } from "@/lib/utils";

/** A button-looking <label> around a hidden file input (keyboard accessible via the input). */
export function FileButton({
  accept,
  loading,
  disabled,
  variant = "default",
  onFile,
  children,
}: {
  accept: string;
  loading?: boolean;
  disabled?: boolean;
  variant?: "default" | "outline" | "secondary";
  onFile: (file: File) => void;
  children: ReactNode;
}) {
  const inactive = Boolean(loading || disabled);
  return (
    <label
      className={cn(
        buttonVariants({ variant, size: "sm" }),
        "cursor-pointer focus-within:ring-2 focus-within:ring-ring",
        inactive && "pointer-events-none opacity-50",
      )}
    >
      {loading && <Loader2 className="animate-spin" />}
      {children}
      <input
        type="file"
        accept={accept}
        className="sr-only"
        disabled={inactive}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onFile(file);
          event.target.value = ""; // allow picking the same file again
        }}
      />
    </label>
  );
}
