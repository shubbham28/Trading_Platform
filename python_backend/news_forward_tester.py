"""
News-Based Forward Tester
Uses sentiment analysis to score daily headlines and simulate paper trades
Selects top stocks based on news sentiment + volume
Provides forward-looking trade signals for upcoming market sessions
"""
import os
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
from pydantic import BaseModel

# Try to import transformers for sentiment analysis
try:
    from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False


class NewsSignal(BaseModel):
    """News-based trading signal"""
    symbol: str
    timestamp: datetime
    sentiment_score: float  # -1 to 1
    sentiment_label: str  # positive, negative, neutral
    news_count: int
    volume_score: float
    action: str  # buy, sell, hold
    confidence: float
    reason: str


class ForwardTestResult(BaseModel):
    """Forward test result"""
    signal_date: str
    trade_date: str
    signals: List[Dict[str, Any]]
    simulated_trades: List[Dict[str, Any]]
    cumulative_return: float
    total_trades: int
    winning_trades: int


class NewsForwardTester:
    """News-based forward tester for predicting upcoming trades"""
    
    def __init__(self, results_dir: Optional[str] = None):
        """
        Initialize news forward tester
        
        Args:
            results_dir: Directory to store results (default: backend/results/news_signals)
        """
        if results_dir is None:
            backend_dir = Path(__file__).parent
            results_dir = backend_dir / 'results' / 'news_signals'
        
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize sentiment model if available
        self.sentiment_analyzer = None
        if HAS_TRANSFORMERS:
            try:
                # Use FinBERT or distilbert for financial sentiment
                model_name = "ProsusAI/finbert"
                self.sentiment_analyzer = pipeline(
                    "sentiment-analysis",
                    model=model_name,
                    tokenizer=model_name
                )
            except Exception as e:
                print(f"Could not load FinBERT model, using fallback: {e}")
                try:
                    # Fallback to distilbert
                    self.sentiment_analyzer = pipeline(
                        "sentiment-analysis",
                        model="distilbert-base-uncased-finetuned-sst-2-english"
                    )
                except Exception:
                    print("Could not load sentiment model")
    
    def analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Analyze sentiment of text
        
        Args:
            text: Text to analyze
        
        Returns:
            Dictionary with sentiment score and label
        """
        if self.sentiment_analyzer is None:
            # Fallback to simple keyword-based sentiment
            return self._fallback_sentiment(text)
        
        try:
            result = self.sentiment_analyzer(text[:512])[0]  # Limit to 512 chars
            
            # Map labels to scores
            label = result['label'].lower()
            score = result['score']
            
            # Convert to -1 to 1 scale
            if 'positive' in label or label == 'label_2':
                sentiment_score = score
            elif 'negative' in label or label == 'label_0':
                sentiment_score = -score
            else:
                sentiment_score = 0
            
            return {
                'score': sentiment_score,
                'label': 'positive' if sentiment_score > 0 else 'negative' if sentiment_score < 0 else 'neutral',
                'confidence': abs(score)
            }
        except Exception as e:
            print(f"Sentiment analysis error: {e}")
            return self._fallback_sentiment(text)
    
    def _fallback_sentiment(self, text: str) -> Dict[str, Any]:
        """
        Fallback sentiment analysis using keyword matching
        
        Args:
            text: Text to analyze
        
        Returns:
            Dictionary with sentiment score and label
        """
        text_lower = text.lower()
        
        positive_keywords = [
            'gain', 'surge', 'rally', 'up', 'high', 'profit', 'growth',
            'beat', 'outperform', 'bullish', 'upgrade', 'strong'
        ]
        negative_keywords = [
            'loss', 'drop', 'fall', 'down', 'low', 'miss', 'decline',
            'weak', 'underperform', 'bearish', 'downgrade', 'cut'
        ]
        
        positive_count = sum(1 for word in positive_keywords if word in text_lower)
        negative_count = sum(1 for word in negative_keywords if word in text_lower)
        
        total = positive_count + negative_count
        if total == 0:
            return {'score': 0, 'label': 'neutral', 'confidence': 0.5}
        
        score = (positive_count - negative_count) / total
        
        return {
            'score': score,
            'label': 'positive' if score > 0.2 else 'negative' if score < -0.2 else 'neutral',
            'confidence': min(abs(score) + 0.5, 1.0)
        }
    
    def generate_signals(
        self,
        news_data: List[Dict[str, Any]],
        market_data: Optional[Dict[str, pd.DataFrame]] = None,
        top_n: int = 5
    ) -> List[NewsSignal]:
        """
        Generate trading signals based on news sentiment
        
        Args:
            news_data: List of news items with 'symbol', 'headline', 'timestamp'
            market_data: Optional dict of symbol -> DataFrame with volume data
            top_n: Number of top signals to return
        
        Returns:
            List of news-based trading signals
        """
        # Aggregate news by symbol
        symbol_news: Dict[str, List[Dict]] = {}
        for item in news_data:
            symbol = item.get('symbol')
            if symbol:
                if symbol not in symbol_news:
                    symbol_news[symbol] = []
                symbol_news[symbol].append(item)
        
        # Score each symbol
        signals = []
        for symbol, news_items in symbol_news.items():
            # Analyze sentiment for all news
            sentiments = []
            for item in news_items:
                headline = item.get('headline', '')
                sentiment = self.analyze_sentiment(headline)
                sentiments.append(sentiment)
            
            # Aggregate sentiment
            avg_score = np.mean([s['score'] for s in sentiments])
            avg_confidence = np.mean([s['confidence'] for s in sentiments])
            
            # Calculate volume score if market data available
            volume_score = 1.0
            if market_data and symbol in market_data:
                df = market_data[symbol]
                if 'volume' in df.columns and len(df) > 20:
                    recent_volume = df['volume'].iloc[-5:].mean()
                    avg_volume = df['volume'].iloc[-20:].mean()
                    volume_score = recent_volume / avg_volume if avg_volume > 0 else 1.0
            
            # Determine action
            if avg_score > 0.3 and volume_score > 1.2:
                action = 'buy'
                confidence = min((abs(avg_score) + volume_score - 1) / 2, 1.0)
            elif avg_score < -0.3:
                action = 'sell'
                confidence = min(abs(avg_score) * avg_confidence, 1.0)
            else:
                action = 'hold'
                confidence = 0.5
            
            sentiment_label = 'positive' if avg_score > 0.2 else 'negative' if avg_score < -0.2 else 'neutral'
            
            signal = NewsSignal(
                symbol=symbol,
                timestamp=datetime.now(),
                sentiment_score=avg_score,
                sentiment_label=sentiment_label,
                news_count=len(news_items),
                volume_score=volume_score,
                action=action,
                confidence=confidence,
                reason=f'{len(news_items)} news items, avg sentiment={avg_score:.2f}, vol_ratio={volume_score:.2f}x'
            )
            signals.append(signal)
        
        # Sort by confidence and return top N
        signals.sort(key=lambda x: x.confidence, reverse=True)
        return signals[:top_n * 2]  # Return top positive and negative
    
    def save_signals(self, signals: List[NewsSignal], date: Optional[str] = None):
        """
        Save signals to file
        
        Args:
            signals: List of signals to save
            date: Date string (YYYY-MM-DD), defaults to today
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        filepath = self.results_dir / f'signals_{date}.json'
        
        data = {
            'date': date,
            'timestamp': datetime.now().isoformat(),
            'signals': [s.model_dump() for s in signals]
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"Signals saved to {filepath}")
    
    def load_signals(self, date: Optional[str] = None) -> Optional[List[NewsSignal]]:
        """
        Load signals from file
        
        Args:
            date: Date string (YYYY-MM-DD), defaults to today
        
        Returns:
            List of signals or None if not found
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        filepath = self.results_dir / f'signals_{date}.json'
        
        if not filepath.exists():
            return None
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        signals = [NewsSignal(**s) for s in data['signals']]
        return signals
    
    def simulate_forward_test(
        self,
        signals: List[NewsSignal],
        market_data: Dict[str, pd.DataFrame],
        capital_per_trade: float = 1000.0
    ) -> ForwardTestResult:
        """
        Simulate paper trades based on signals
        
        Args:
            signals: Trading signals
            market_data: Historical price data for simulation
            capital_per_trade: Capital to allocate per trade
        
        Returns:
            Forward test results
        """
        simulated_trades = []
        total_return = 0.0
        winning_trades = 0
        
        for signal in signals:
            if signal.action in ['buy', 'sell'] and signal.symbol in market_data:
                df = market_data[signal.symbol]
                
                if len(df) < 2:
                    continue
                
                # Simulate entry at next open
                entry_price = df.iloc[-1]['close']  # Use last close as proxy
                
                # Simulate exit after one day (simplified)
                # In production, you'd track across multiple days
                exit_price = entry_price * (1 + np.random.normal(0.01, 0.02))  # Simulated price change
                
                if signal.action == 'buy':
                    pnl = (exit_price - entry_price) / entry_price
                else:
                    pnl = (entry_price - exit_price) / entry_price
                
                pnl_dollars = pnl * capital_per_trade
                total_return += pnl_dollars
                
                if pnl > 0:
                    winning_trades += 1
                
                simulated_trades.append({
                    'symbol': signal.symbol,
                    'action': signal.action,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': pnl,
                    'pnl_dollars': pnl_dollars,
                    'sentiment_score': signal.sentiment_score
                })
        
        signal_date = datetime.now().strftime('%Y-%m-%d')
        trade_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        result = ForwardTestResult(
            signal_date=signal_date,
            trade_date=trade_date,
            signals=[s.model_dump() for s in signals],
            simulated_trades=simulated_trades,
            cumulative_return=total_return,
            total_trades=len(simulated_trades),
            winning_trades=winning_trades
        )
        
        # Save result
        result_file = self.results_dir / f'forward_test_{signal_date}.json'
        with open(result_file, 'w') as f:
            json.dump(result.model_dump(), f, indent=2, default=str)
        
        return result
    
    def get_latest_results(self) -> Optional[ForwardTestResult]:
        """
        Get the most recent forward test results
        
        Returns:
            Latest forward test result or None
        """
        result_files = sorted(self.results_dir.glob('forward_test_*.json'), reverse=True)
        
        if not result_files:
            return None
        
        with open(result_files[0], 'r') as f:
            data = json.load(f)
        
        return ForwardTestResult(**data)
