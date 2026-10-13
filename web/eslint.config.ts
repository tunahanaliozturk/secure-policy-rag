import js from '@eslint/js'
import { defineConfig } from 'eslint/config'
import prettier from 'eslint-config-prettier'
import vue from 'eslint-plugin-vue'
import a11y from 'eslint-plugin-vuejs-accessibility'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig(
  {
    // The two schema files are generated from the server's OpenAPI documents (npm run gen:api), not written.
    ignores: ['dist', 'coverage', 'playwright-report', 'test-results', '.lighthouseci', 'src/shared/api/*.schema.d.ts'],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  ...vue.configs['flat/recommended'],
  ...a11y.configs['flat/recommended'],
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        parser: tseslint.parser,
        projectService: true,
        extraFileExtensions: ['.vue'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // A number in a template string is what it looks like.
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
      '@typescript-eslint/no-unused-vars': ['error', { varsIgnorePattern: '^_', argsIgnorePattern: '^_' }],
      // `() => router.push(...)` passes nothing on; braces around it would say no more.
      '@typescript-eslint/no-confusing-void-expression': ['error', { ignoreArrowShorthand: true }],
      // A label names its field by id here; nesting the field inside it as well would add nothing.
      'vuejs-accessibility/label-has-for': ['error', { required: { some: ['nesting', 'id'] } }],
      'vue/no-v-html': 'error',
      'vue/block-lang': ['error', { script: { lang: 'ts' } }],
      'vue/component-api-style': ['error', ['script-setup']],
      'vue/define-emits-declaration': ['error', 'type-based'],
      'vue/define-props-declaration': ['error', 'type-based'],
      // The content security policy allows no inline style, so a bound style attribute would be dropped by the browser.
      'vue/no-restricted-syntax': [
        'error',
        { selector: "VAttribute[key.argument.name='style']", message: 'The CSP blocks inline styles. Use a class.' },
        { selector: "VAttribute[key.name='style']", message: 'The CSP blocks inline styles. Use a class.' },
      ],
    },
  },
  prettier,
)
