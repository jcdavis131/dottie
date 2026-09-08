import { defineConfig } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

export default defineConfig([
  {
    // Dormant browser-local simulation is excluded because the product contract forbids imports; it is not release capability.
    ignores: ["app/acd/**"],
  },
  ...nextVitals,
  ...nextTypeScript,
]);
