const path = require('node:path');
const { container: { ModuleFederationPlugin } } = require('webpack');
const HtmlWebpackPlugin = require('html-webpack-plugin');

const remoteBase = '/remote/fund-cmt-auto/';

module.exports = (_env, argv) => ({
  context: __dirname,
  mode: argv.mode || 'production',
  entry: './src/main.tsx',
  output: {
    path: path.resolve(__dirname, 'dist'),
    // Chunks/fonts follow the script origin, including host -> localhost:3030 dev.
    publicPath: 'auto',
    uniqueName: 'fundCmtAuto',
    filename: '[name].[contenthash].js',
    chunkFilename: 'assets/[name].[contenthash].js',
    assetModuleFilename: 'assets/[name].[contenthash][ext]',
    clean: true,
    crossOriginLoading: 'anonymous',
  },
  resolve: { extensions: ['.tsx', '.ts', '.js'] },
  module: { rules: [
    { test: /\.tsx?$/, exclude: /node_modules/, loader: 'esbuild-loader', options: { loader: 'tsx', target: 'es2022', jsx: 'automatic' } },
    { test: /\.css$/, use: [{ loader: 'css-loader', options: { exportType: 'string' } }] },
    { test: /\.(woff2?|ttf|svg|png)$/, type: 'asset/resource' },
  ] },
  plugins: [
    new ModuleFederationPlugin({
      name: 'fundCmtAuto',
      filename: 'remoteEntry.js',
      exposes: { './App': './src/RemoteApp.tsx' },
      shared: {
        react: { singleton: true, strictVersion: true, requiredVersion: '^18.2.0' },
        'react-dom': { singleton: true, strictVersion: true, requiredVersion: '^18.2.0' },
        // v7 data router (useBlocker) must not consume host's v6 singleton.
      },
    }),
    new HtmlWebpackPlugin({ template: './index.html', publicPath: remoteBase, excludeChunks: ['fundCmtAuto'] }),
  ],
  devtool: argv.mode === 'development' ? 'source-map' : false,
  devServer: {
    host: '0.0.0.0',
    port: 3030,
    open: false,
    hot: false,
    liveReload: false,
    headers: { 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'no-store' },
    devMiddleware: { publicPath: remoteBase },
    historyApiFallback: {
      rewrites: [
        { from: /^\/remote\/fund-cmt-auto\/(?:reports(?:\/[^.]*)?)?$/, to: `${remoteBase}index.html` },
        { from: /./, to: ({ parsedUrl }) => parsedUrl.pathname },
      ],
    },
    setupMiddlewares: (middlewares) => {
      middlewares.unshift({ name: 'remote-root-redirect', middleware: (req, res, next) => {
        if (['/', '/remote/fund-cmt-auto'].includes(req.url.split('?')[0])) {
          res.writeHead(302, { Location: remoteBase });
          res.end();
        } else next();
      } });
      return middlewares;
    },
    proxy: [{ context: [`${remoteBase}api/`], target: 'http://localhost:8000', pathRewrite: { '^/remote/fund-cmt-auto': '' } }],
  },
  performance: { hints: false },
});
