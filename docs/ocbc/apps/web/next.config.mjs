/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ["@tax-build/db", "@tax-build/parser", "@tax-build/tax-engine"],
  experimental: {
    serverComponentsExternalPackages: ["better-sqlite3"]
  }
};

export default nextConfig;