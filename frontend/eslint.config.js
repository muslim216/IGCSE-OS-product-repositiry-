import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

/**
 * Flat config (ESLint 9). Chosen to catch bugs, not to enforce taste — the same
 * standard the backend's ruff config is held to.
 *
 * `tsc -b` already runs in CI and covers types, so nothing here duplicates the
 * type checker. What ESLint adds is the class of mistake types cannot see: a
 * hook called conditionally, a dependency array missing the value it closes
 * over. Those are the defects that reach a user.
 *
 * CI runs this with `--max-warnings 0`. A warning nobody is obliged to clear
 * accumulates until the output is scrolled past rather than read, and the point
 * of turning linting on is to have a signal that means something on the day it
 * fires. Warning severity here marks that a rule is advisory in *kind* — it can
 * have a legitimate exception — not that it is optional to resolve. The
 * exception is written as an `eslint-disable-next-line` with a reason, which is
 * a decision on the record rather than a number creeping upward.
 */
export default tseslint.config(
  { ignores: ["dist", "coverage", "node_modules"] },

  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      // Enabled by name rather than by preset. Every config this plugin ships in
      // v7 pulls in the sixteen React Compiler rules (purity, immutability,
      // set-state-in-effect and the rest), which are a real decision about how
      // the app is written — not a lint baseline, and not something to acquire
      // as a side effect of turning linting on. These two are the ones that
      // catch defects a user would feel.
      //
      // Deliberately NOT enabled: react-refresh/only-export-components. It fires
      // on six files, and every one is the ordinary React pattern of a hook or a
      // pure helper living beside what it serves — useAuth by AuthContext,
      // useToast by the toast, matchesFilter by the table it filters (and that
      // one is unit-tested where it stands). Clearing it means splitting coupled
      // code across more files to make a dev-server reload marginally faster.
      // That is a cost paid by every future reader for a benefit no user ever
      // sees, so the plugin is not installed at all rather than left on as noise.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",

      // An unused parameter is usually a rename that did not finish. The
      // underscore prefix is the escape hatch for the genuine cases — a callback
      // whose third argument you must accept in order to reach the fourth.
      //
      // ignoreRestSiblings covers `({ key, ...rest }) => rest`, where naming a
      // binding is how you remove it: the name is unused because that is the
      // point. Suppressing it by renaming to `_key` would be marking correct
      // code as an exception.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
    },
  },

  // Tests read fixtures off disk (see contrast.test.ts, which parses index.css
  // rather than importing it) so they need node globals on top of browser ones.
  {
    files: ["src/test/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },

  // Config files run in node, before any bundler touches them.
  {
    files: ["*.config.{js,ts}", "vite.config.ts"],
    languageOptions: { globals: globals.node },
  },
);
