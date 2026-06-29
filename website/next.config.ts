import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/install", destination: "/install.sh" }];
  },
  async headers() {
    return [
      {
        source: "/install.sh",
        headers: [{ key: "Content-Type", value: "text/x-shellscript; charset=utf-8" }],
      },
    ];
  },
};

export default nextConfig;
