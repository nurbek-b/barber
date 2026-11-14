import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/node_modules/**",
      "backend/**",
      "**/coverage/**",
      "**/playwright-report/**",
      "packages/api-client/src/schema.d.ts",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/consistent-type-imports": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.name='parseFloat']",
          message: "Money is integer minor units: never parse floats (use parseMoneyInput).",
        },
      ],
    },
  },
  {
    files: ["**/*.{js,mjs}", "**/scripts/**"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["apps/*/public/**/*.js"],
    languageOptions: { globals: { ...globals.browser }, sourceType: "script" },
  },
);
