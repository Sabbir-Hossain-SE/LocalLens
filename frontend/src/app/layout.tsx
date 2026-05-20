import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'LocalLens — AI Local Discovery',
  description:
    'Discover local businesses with AI. Ask natural-language questions and get ranked, summarized results with scores, maps, and reviews.',
  keywords: ['local business', 'AI search', 'restaurant finder', 'local discovery'],
  authors: [{ name: 'LocalLens' }],
  openGraph: {
    title: 'LocalLens',
    description: 'AI-powered local business discovery',
    type: 'website',
  },
};

export const viewport: Viewport = {
  themeColor: '#0a0f1a',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-surface-deep text-slate-100 antialiased">
        {children}
      </body>
    </html>
  );
}
