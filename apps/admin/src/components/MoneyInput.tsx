import { parseMoneyInput } from "@barber/ui";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui";
import { toMajorInput } from "@/lib/format";

/**
 * Edits money in major units ("1 500,50") and reports integer minor units (150050) —
 * never a float. `null` while the text is empty or invalid.
 */
export function MoneyInput({
  value,
  onChange,
  id,
  placeholder,
  allowEmpty = false,
  ...rest
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  id?: string;
  placeholder?: string;
  allowEmpty?: boolean;
  "aria-label"?: string;
}) {
  const [text, setText] = useState(() => toMajorInput(value));
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    // external value changed (form reset): sync unless the user is mid-typing the same value
    if (parseMoneyInput(text) !== value) setText(toMajorInput(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <Input
      id={id}
      inputMode="decimal"
      placeholder={placeholder}
      value={text}
      aria-invalid={invalid}
      className={invalid ? "border-destructive" : undefined}
      onChange={(event) => {
        const next = event.target.value;
        setText(next);
        if (allowEmpty && next.trim() === "") {
          setInvalid(false);
          onChange(null);
          return;
        }
        const parsed = parseMoneyInput(next);
        setInvalid(parsed === null);
        onChange(parsed);
      }}
      {...rest}
    />
  );
}
