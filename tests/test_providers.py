from unittest import TestCase

from apps.control_plane.providers import ComfyUIProvider, Kuajing84Provider, ProviderUnavailableError


class StubComfyUIProvider(ComfyUIProvider):
    def _request(self, method, path, **kwargs):
        return {
            "system": {"comfyui_version": "0.27.0"},
            "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 4060 Laptop GPU"}],
        }


class ComfyUIProviderTest(TestCase):
    def test_health_exposes_runtime_version_and_device(self):
        health = StubComfyUIProvider().healthcheck()

        self.assertEqual(health.status, "ok")
        self.assertEqual(health.detail, "0.27.0 · cuda:0 NVIDIA GeForce RTX 4060 Laptop GPU")


class StubKuajing84Provider(Kuajing84Provider):
    def __init__(self, responses):
        super().__init__(client_secret="secret", app_uid="uid")
        self.responses = iter(responses)
        self.requests = []

    def _request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return next(self.responses)


class Kuajing84ProviderTest(TestCase):
    def test_reads_raw_cost_and_weight_fields_without_reinterpreting_them(self):
        provider = StubKuajing84Provider(
            [
                {"code": 1, "access_token": "token"},
                {
                    "code": 1,
                    "data": {
                        "count": 1,
                        "list": [
                            {
                                "id": 123,
                                "price": 15.5,
                                "freight": 5,
                                "extra": 10,
                                "fees_price": 2,
                                "system_price": 1,
                                "unit_price": 0.5,
                            }
                        ],
                    },
                },
                {"code": 1, "data": {"weight": 1.5, "chargeweight": 3.2}},
                {
                    "code": 1,
                    "data": {"core_data": [{"id": 1, "name": "拆包验货", "gold": 5}], "optional_data": []},
                },
            ]
        )

        self.assertEqual(provider.fetch_access_token(), "token")
        order = provider.list_orders({"page": 1, "limit": 1})["list"][0]
        weight = provider.order_out_info(order_id=123)
        services = provider.warehouse_services(warehouse_id=1, platform_id=1)

        self.assertEqual(order["freight"], 5)
        self.assertEqual(order["fees_price"], 2)
        self.assertEqual(weight["chargeweight"], 3.2)
        self.assertEqual(services["core_data"][0]["gold"], 5)
        self.assertEqual(provider.requests[1][1], "/erpapi/orderlist/search")
        self.assertEqual(provider.requests[1][2]["headers"]["authorization"], "token")

    def test_fails_closed_for_missing_credentials_or_invalid_response(self):
        with self.assertRaisesRegex(ValueError, "client_secret and app_uid"):
            Kuajing84Provider(client_secret="", app_uid="")

        provider = StubKuajing84Provider([{"code": 0, "message": "denied"}])
        with self.assertRaisesRegex(ProviderUnavailableError, "non-success"):
            provider.fetch_access_token()
