import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'jarvis-agent',
  tagline: '스스로 사고하고 먼저 행동하는 개인 AI 비서',
  favicon: 'img/favicon.svg',
  url: 'https://ash-hun.github.io',
  baseUrl: '/jarvis-agent/',
  organizationName: 'ash-hun',
  projectName: 'jarvis-agent',
  onBrokenLinks: 'throw',
  i18n: {defaultLocale: 'ko', locales: ['ko']},
  stylesheets: [
    {
      href: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600&display=swap',
      type: 'text/css',
    },
  ],
  markdown: {mermaid: true},
  themes: ['@docusaurus/theme-mermaid'],
  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/ash-hun/jarvis-agent/tree/main/website/',
        },
        blog: false,
        theme: {customCss: './src/css/custom.css'},
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
    colorMode: {defaultMode: 'dark', respectPrefersColorScheme: true},
    navbar: {
      title: 'jarvis-agent',
      logo: {alt: 'jarvis-agent', src: 'img/logo.svg'},
      items: [
        {type: 'docSidebar', sidebarId: 'docs', position: 'left', label: '문서'},
        {href: 'https://github.com/ash-hun/jarvis-agent', label: 'GitHub', position: 'right'},
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: '레포',
          items: [
            {label: 'GitHub', href: 'https://github.com/ash-hun/jarvis-agent'},
            {label: 'API 명세', href: 'https://github.com/ash-hun/jarvis-agent/blob/main/docs/api-spec.md'},
            {label: '화면 명세', href: 'https://github.com/ash-hun/jarvis-agent/blob/main/docs/screen-spec.md'},
          ],
        },
      ],
      copyright: `MIT License. Built with Docusaurus.`,
    },
    prism: {theme: prismThemes.github, darkTheme: prismThemes.nightOwl, additionalLanguages: ['bash', 'yaml', 'json']},
    mermaid: {theme: {light: 'neutral', dark: 'dark'}},
  } satisfies Preset.ThemeConfig,
};

export default config;
