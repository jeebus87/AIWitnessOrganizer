import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

// Force all pages to be dynamically rendered - no edge caching
export const dynamic = 'force-dynamic';
export const revalidate = 0;

const inter = Inter({
  subsets: ["latin"],
});

// DEBUG: Change title to verify deployment - BUILD 003
export const metadata: Metadata = {
  title: "AI Witness Organizer - BUILD 003 - 20260118_0245",
  description: "Automated Legal Witness Extraction System",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // DEBUG: Log that root layout is rendering
  console.log("[RootLayout] Rendering - BUILD 001");

  return (
    <html lang="en">
      <body className={`${inter.className} antialiased`}>
        {/* DEBUG: Absolutely positioned banner that should show on ALL pages */}
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          backgroundColor: 'red',
          color: 'white',
          padding: '10px',
          textAlign: 'center',
          zIndex: 99999,
          fontSize: '18px',
          fontWeight: 'bold'
        }}>
          DEBUG BUILD 003 - 20260118_0245 - If you see this, deployment works!
        </div>
        <div style={{ paddingTop: '50px' }}>
          <Providers>{children}</Providers>
        </div>
      </body>
    </html>
  );
}
