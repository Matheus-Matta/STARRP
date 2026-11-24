// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ['dist/*'],
  },
  {
    // `@front/...` = arquivos da retaguarda (frontend/src), resolvidos pelo metro.config.js.
    rules: { 'import/no-unresolved': ['error', { ignore: ['^@front/'] }] },
  },
]);
