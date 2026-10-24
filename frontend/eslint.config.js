import pluginVue from "eslint-plugin-vue";
import tseslint from "typescript-eslint";

// Entra o que aponta defeito; fica de fora o que só discorda de estilo.
export default tseslint.config(
  { ignores: ["dist", "src/api/schema.d.ts"] },
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/essential"],
  {
    files: ["**/*.vue"],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
  },
  {
    rules: {
      // Telas como "LoginPage" e "PdvPage" têm nome de uma palavra + sufixo de propósito.
      "vue/multi-word-component-names": "off",
    },
  },
);
