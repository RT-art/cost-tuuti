import time
import boto3
import json
import requests
from datetime import datetime, timedelta
import os
from decimal import Decimal
from botocore.exceptions import ClientError

def get_cost_data():
    """AWSのコスト情報を取得する関数"""
    client = boto3.client('ce')
    
    # 日付の設定（今日と昨日）
    end_date = datetime.today().strftime('%Y-%m-%d')
    start_date = (datetime.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    try:
        # 全体のコストを取得
        response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date,
                'End': end_date
            },
            Granularity='DAILY',
            Metrics=['UnblendedCost'],
            GroupBy=[
                {'Type': 'DIMENSION', 'Key': 'SERVICE'}
            ]
        )

        # 月間予測コストの取得（エラーハンドリング追加）
        try:
            forecast_response = client.get_cost_forecast(
                TimePeriod={
                    'Start': datetime.today().strftime('%Y-%m-%d'),
                    'End': (datetime.today() + timedelta(days=30)).strftime('%Y-%m-%d')
                },
                Metric='UNBLENDED_COST',
                Granularity='MONTHLY'
            )
        except ClientError as e:
            if e.response['Error']['Code'] == 'DataUnavailableException':
                print("予測データが利用できません。現在のコストのみ表示します。")
                forecast_response = {
                    'Total': {
                        'Amount': "N/A",
                        'Unit': 'USD'
                    }
                }
            else:
                raise
        
        return {
            'daily_cost': response,
            'forecast': forecast_response
        }
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        raise

def format_cost_message(cost_data):
    """コスト情報をSlackメッセージ形式に整形する関数"""
    daily_costs = cost_data['daily_cost']['ResultsByTime'][0]
    forecast = cost_data['forecast']
    
    # サービス別コストの計算
    service_costs = []
    for group in daily_costs['Groups']:
        service = group['Keys'][0]
        amount = float(group['Metrics']['UnblendedCost']['Amount'])
        if amount > 0.01:  # 1セント以上のコストのみ表示
            service_costs.append((service, amount))
    
    # コストの高い順にソート
    service_costs.sort(key=lambda x: x[1], reverse=True)
    
    # 予測コストの取得（エラー時は "データ不足" と表示）
    forecast_amount = forecast['Total']['Amount']
    if forecast_amount == "N/A":
        forecast_display = "データ不足"
    else:
        forecast_display = f"${float(forecast_amount):.2f}"
    
    # メッセージブロックの作成
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"AWS利用料金レポート ({datetime.now().strftime('%Y-%m-%d')})",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*昨日の総利用料金:*\n${float(sum(cost[1] for cost in service_costs)):.2f}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*今月の予測総額:*\n{forecast_display}"
                }
            ]
        },
        {
            "type": "divider"
        }
    ]
    
    # サービス別コストの追加
    service_cost_text = "*サービス別内訳:*\n"
    for service, amount in service_costs[:10]:  # 上位10サービスのみ表示
        service_cost_text += f"• {service}: ${amount:.2f}\n"
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": service_cost_text
        }
    })
    
    return {
        "blocks": blocks
    }

def notify_slack(message, retry_count=3):
    """Slackに通知を送る関数（リトライ機能付き）"""
    webhook_url = os.environ['SLACK_WEBHOOK_URL']
    
    for attempt in range(retry_count):
        try:
            response = requests.post(webhook_url, json=message)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if attempt == retry_count - 1:  # 最後の試行
                print(f"Failed to send Slack notification after {retry_count} attempts: {str(e)}")
                raise
            print(f"Retry {attempt + 1}/{retry_count} failed: {str(e)}")
            time.sleep(1)  # 1秒待ってリトライ

def lambda_handler(event, context):
    """Lambda関数のメインハンドラー"""
    try:
        # コスト情報の取得
        cost_data = get_cost_data()
        
        # メッセージの整形
        message = format_cost_message(cost_data)
        
        # Slackに通知
        notify_slack(message)
        
        return {
            'statusCode': 200,
            'body': json.dumps('Cost notification sent successfully!')
        }
    except Exception as e:
        error_message = f"Error occurred: {str(e)}"
        print(error_message)
        
        # エラー時もSlackに通知
        try:
            error_notification = {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*AWS Cost Notification Error*\n{error_message}"
                        }
                    }
                ]
            }
            notify_slack(error_notification)
        except:
            print("Failed to send error notification to Slack")
        
        return {
            'statusCode': 500,
            'body': json.dumps(error_message)
        }