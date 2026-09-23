/** @type {import('next').NextConfig} */
const nextConfig = {
  // SSR enabled — dynamic thin UI + /api/pair/* live pairing queue
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  // public/starter/index.html is also served at the clean URL the site links to.
  async rewrites() {
    return [{ source: "/starter", destination: "/starter/index.html" }];
  },
};
export default nextConfig;
