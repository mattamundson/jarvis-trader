"""
FreqAI Retraining Job
=====================
Automates the lifecycle of fetching data (OpenBB),
preparing features (DataKitchen), and retraining models.
"""

import logging

from learning.freqai_kitchen import FreqaiDataKitchen
from learning.model_drawer import ModelDrawer

logger = logging.getLogger("jarvis_trader.learning.retrain_job")

class FreqaiRetrainJob:
    def __init__(self, db_manager, openbb_adapter):
        self.db = db_manager
        self.openbb = openbb_adapter
        self.kitchen = FreqaiDataKitchen(window_size=50)
        self.drawer = ModelDrawer()
        self.is_running = False

    async def run_training_cycle(self, symbol: str):
        """
        Full cycle: Data -> Kitchen -> Model.
        """
        if self.is_running:
            return

        self.is_running = True
        logger.info(f"🚀 Starting FreqAI retraining cycle for {symbol}")

        try:
            # 1. Fetch historical data via OpenBB Hub
            df = await self.openbb.get_historical_data(symbol, days=365)
            if df.empty:
                logger.warning(f"No data found for {symbol} retraining.")
                return

            # 2. Prepare features via Kitchen
            X, y = self.kitchen.prepare_data(df, target_col="close")

            # 3. Train XGBoost Model
            import xgboost as xgb
            model = xgb.XGBRegressor(n_estimators=100, learning_rate=0.1, max_depth=5)
            model.fit(X, y)

            # 4. Save via Drawer
            self.drawer.save_model(model, symbol)
            logger.info(f"Training complete. Features shape: {X.shape}, Model persisted.")

            # 4. Save metadata to DB
            # self.db.save_model_metadata(symbol, version=datetime.now().isoformat())

        except Exception as e:
            logger.error(f"Retraining cycle failed: {e}")
        finally:
            self.is_running = False
            logger.info("Retraining cycle finished.")

    def schedule_nightly(self, scheduler):
        """Register the job with the APScheduler."""
        scheduler.add_job(
            self.run_training_cycle,
            "cron",
            hour=1,
            minute=0,
            args=["SPY"], # Example
            id="freqai_retrain_spy"
        )
