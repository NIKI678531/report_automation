const path = require('node:path');
const { container: { ModuleFederationPlugin } } = require('webpack');

module.exports = {
  mode: 'development',
  context: __dirname,
  entry: './entry.js',
  output: { path: path.resolve(__dirname, '../../../var/remote-contract/host'), publicPath: '/host-assets/', uniqueName: 'contractHost', clean: true },
  module: { rules: [{ test: /\.jsx$/, loader: 'esbuild-loader', options: { loader: 'jsx', jsx: 'automatic' } }] },
  plugins: [new ModuleFederationPlugin({ name: 'host', shared: {
    react: { singleton: true, requiredVersion: '^18.2.0' },
    'react-dom': { singleton: true, requiredVersion: '^18.2.0' },
    'host-react-router-dom': { shareKey: 'react-router-dom', singleton: true, requiredVersion: '^6.8.0' },
  } })],
  devtool: false,
};
