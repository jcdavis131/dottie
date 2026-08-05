/** @type {import('next').NextConfig} */
const nextConfig = {
  // compatible with `output: 'export'` for static hosting,
  // but defaults to Vercel's hybrid for serverless functions.
  // To export statically: uncomment below.
  // output: 'export',
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
