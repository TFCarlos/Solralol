// Keep the offline storage assistant outside the regular single-instance app.
const args = process.argv.slice(1);
const migrationIndex = args.indexOf('--solralol-storage-migration');
if (migrationIndex >= 0) {
  const configPath = args[migrationIndex + 1];
  require('./migration-assistant.cjs').start(configPath);
} else {
  require('./index.cjs');
}
