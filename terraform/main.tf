# AWSプロバイダーの設定
provider "aws" {
  region = "ap-northeast-1"  # 東京リージョン
}

# Terraformの設定
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"  # AWSプロバイダーのバージョン
    }
  }
}

# Lambda用のIAMロールの作成
#ゴールはlambdaにcostexplorerアクセスの許可を与える事。ここでは「lambdaがなんかする」と定義
resource "aws_iam_role" "lambda_role" {
  name = "cost_tuuti_lambda_role"  # IAMロールの名前

  # 信頼ポリシー：誰がこのロールを使えるか
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# Lambda用のポリシーをIAMロールにアタッチ　
resource "aws_iam_role_policy" "lambda_policy" {
  name = "cost_notification_lambda_policy"
  role = aws_iam_role.lambda_role.id  # 先ほど作ったロールを参照

  # ここでcost explorerのアクセスの許可設定
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",  # aws全体のコスト見れる
          "ce:GetCostForecast"   # これからのコスト予測見れる
        ]
        Resource = "*"  # aws全体のコスト分析したいため、見れる対象は*になる
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"  # CloudWatchログの権限
      }
    ]
  })
}

# Lambda関数の定義
resource "aws_lambda_function" "cost_notification" {
  filename         = "../src/lambda_function.zip"  # Lambda関数のコードを含むZIPファイル
  function_name    = "cost_notification"        # Lambda関数の名前
  role            = aws_iam_role.lambda_role.arn  # 先ほど作成したIAMロールのARN
  handler         = "lambda_function.lambda_handler"  # 実行する関数の指定
  runtime         = "python3.9"                 # Pythonのバージョン
  memory_size     = 256
  timeout         = 10
  environment {
    variables = {
      SLACK_WEBHOOK_URL = var.slack_webhook_url  # Slack WebhookのURL（後で変数として定義）
    }
  }
}

# EventBridge（旧CloudWatch Events）ルールの定義　
#イベントブリッジがないと、ラムダを手動でやんなきゃいけないため、イベント稼働にする
resource "aws_cloudwatch_event_rule" "daily_cost_check" {
  name                = "daily_cost_check"      # ルールの名前
  description         = "毎日コスト通知を実行"   # ルールの説明
  schedule_expression = "cron(0 15 * * ? *)"     # 毎日午前12時に実行
}

# EventBridgeターゲットの設定
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.daily_cost_check.name  # 上で定義したルール
  target_id = "SendToLambda"
  arn       = aws_lambda_function.cost_notification.arn        # Lambda関数のARN
}

# EventBridgeからLambdaを呼び出す権限の設定
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cost_notification.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_cost_check.arn
}