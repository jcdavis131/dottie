/** @type {import('next').NextConfig} */
const nextConfig = {
  // SSR enabled — dynamic thin UI + /api/pair/* live pairing queue
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
};
export default nextConfig;
