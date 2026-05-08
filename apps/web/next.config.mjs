import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./i18n.ts');

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required for Docker COPY of `.next/standalone` (see apps/web/Dockerfile).
  //
  // On Windows, `next build` may fail with EPERM on symlink creation unless
  // Developer Mode / symlink privileges are enabled. We disable standalone by
  // default on win32 to keep local builds working, and allow forcing it via env.
  ...(process.platform === 'win32' && process.env.NEXT_FORCE_STANDALONE !== '1'
    ? {}
    : { output: 'standalone' }),
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    instrumentationHook: true,
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Frame-Options', value: 'ALLOWALL' },
          { key: 'Content-Security-Policy', value: "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org" },
        ],
      },
    ];
  },
};

export default withNextIntl(nextConfig);
