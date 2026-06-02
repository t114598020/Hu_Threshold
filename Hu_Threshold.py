import logging
import os
from typing import Annotated

import vtk

import qt
import ctk
import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import (
    parameterNodeWrapper,
    WithinRange,
)

from slicer import vtkMRMLScalarVolumeNode


#
# Hu_Threshold
#


class Hu_Threshold(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("Hu_Threshold")
        self.parent.categories = ["Segmentation"]
        self.parent.dependencies = []
        self.parent.contributors = ["汪詩揚"]
        self.parent.helpText = _("""
This module runs DentalSegmentator and performs HU-based layered segmentation on any selected segment.
""")
        self.parent.acknowledgementText = _("""
This file was originally developed by Jean-Christophe Fillion-Robin, Kitware Inc., Andras Lasso, PerkLab,
and Steve Pieper, Isomics, Inc. and was partially funded by NIH grant 3P41RR013218-12S1.
""")
        slicer.app.connect("startupCompleted()", registerSampleData)


def registerSampleData():
    import SampleData
    iconsPath = os.path.join(os.path.dirname(__file__), "Resources/Icons")

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="Hu_Threshold",
        sampleName="Hu_Threshold1",
        thumbnailFileName=os.path.join(iconsPath, "Hu_Threshold1.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        fileNames="Hu_Threshold1.nrrd",
        checksums="SHA256:998cb522173839c78657f4bc0ea907cea09fd04e44601f17c82ea27927937b95",
        nodeNames="Hu_Threshold1",
    )

    SampleData.SampleDataLogic.registerCustomSampleDataSource(
        category="Hu_Threshold",
        sampleName="Hu_Threshold2",
        thumbnailFileName=os.path.join(iconsPath, "Hu_Threshold2.png"),
        uris="https://github.com/Slicer/SlicerTestingData/releases/download/SHA256/1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        fileNames="Hu_Threshold2.nrrd",
        checksums="SHA256:1a64f3f422eb3d1c9b093d1a18da354b13bcf307907c66317e2463ee530b7a97",
        nodeNames="Hu_Threshold2",
    )


@parameterNodeWrapper
class Hu_ThresholdParameterNode:
    inputVolume: vtkMRMLScalarVolumeNode
    imageThreshold: Annotated[float, WithinRange(-100, 500)] = 100
    invertThreshold: bool = False
    thresholdedVolume: vtkMRMLScalarVolumeNode
    invertedVolume: vtkMRMLScalarVolumeNode


#
# Hu_ThresholdWidget
#


class Hu_ThresholdWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):

    def __init__(self, parent=None) -> None:
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic = None
        self._segmentationWidget = None
        self._volumeSelector = None
        self._segmentSelector = None
        self._extractButton = None
        self._statusLabel = None

    def setup(self) -> None:
        ScriptedLoadableModuleWidget.setup(self)

        self.logic = Hu_ThresholdLogic()

        # Step 1: DentalSegmentator
        dentalCollapsible = ctk.ctkCollapsibleButton()
        dentalCollapsible.text = "Step 1: DentalSegmentator"
        self.layout.addWidget(dentalCollapsible)
        dentalLayout = qt.QVBoxLayout(dentalCollapsible)

        from DentalSegmentatorLib import SegmentationWidget
        self._segmentationWidget = SegmentationWidget()
        dentalLayout.addWidget(self._segmentationWidget)

        # Step 2: HU Threshold
        mandibleCollapsible = ctk.ctkCollapsibleButton()
        mandibleCollapsible.text = "Step 2: HU Threshold"
        self.layout.addWidget(mandibleCollapsible)
        mandibleFormLayout = qt.QFormLayout(mandibleCollapsible)

        # CT Volume Selector
        self._volumeSelector = slicer.qMRMLNodeComboBox()
        self._volumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
        self._volumeSelector.setMRMLScene(slicer.mrmlScene)
        self._volumeSelector.addEnabled = False
        self._volumeSelector.removeEnabled = False
        self._volumeSelector.noneEnabled = True
        self._volumeSelector.showHidden = False
        self._volumeSelector.setToolTip("選擇對應的 CT Volume")
        mandibleFormLayout.addRow("CT Volume:", self._volumeSelector)

        # Target Segment Selector（主要選擇器）
        self._segmentSelector = slicer.qMRMLSegmentSelectorWidget()
        self._segmentSelector.setMRMLScene(slicer.mrmlScene)
        self._segmentSelector.setToolTip("選擇要進行 HU 分層的 Segment")
        mandibleFormLayout.addRow("Target Segment:", self._segmentSelector)

        # 提示
        instructionLabel = qt.QLabel(
            "流程：\n"
            "1. 先在 Step 1 執行 DentalSegmentator\n"
            "2. 選擇 CT Volume\n"
            "3. 在 Target Segment 中選擇想要分層的 Segment\n"
            "4. 按下下方按鈕\n\n"
            "※ 載入舊場景時請手動選擇 CT Volume"
        )
        instructionLabel.setWordWrap(True)
        mandibleFormLayout.addRow(instructionLabel)

        self._extractButton = qt.QPushButton("Copy Segment && Build HU Layers")
        self._extractButton.toolTip = "複製選擇的 Segment 並建立 HU 分層"
        self._extractButton.enabled = False
        mandibleFormLayout.addRow(self._extractButton)

        self._statusLabel = qt.QLabel("請先在 Step 1 執行 DentalSegmentator")
        self._statusLabel.setWordWrap(True)
        mandibleFormLayout.addRow(self._statusLabel)

        # Signals
        self._segmentationWidget.segmentationNodeSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onSegmentationNodeChanged
        )
        self._segmentSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSegmentSelectorChanged)
        self._extractButton.clicked.connect(self.onExtractMandible)

        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)

        self.layout.addStretch(1)

    def cleanup(self) -> None:
        self.removeObservers()

    def onSceneStartClose(self, caller, event) -> None:
        self._extractButton.enabled = False
        self._statusLabel.text = "請先在 Step 1 執行 DentalSegmentator 或載入已有場景"

    def onSegmentationNodeChanged(self, node):
        """DentalSegmentator 完成後同步更新"""
        if node is None:
            return
        logging.info(f"Segmentation node 已就緒：{node.GetName()}")

        # 同步 CT Volume
        volumeNode = self._segmentationWidget.getCurrentVolumeNode()
        if volumeNode:
            self._volumeSelector.setCurrentNode(volumeNode)

        # 同步 Target Segment Selector
        self._segmentSelector.setCurrentNode(node)

        self._extractButton.enabled = True
        self._statusLabel.text = "已載入 Segmentation，請選擇 Target Segment 後執行"

    def onSegmentSelectorChanged(self, node):
        """當 Target Segment 的 Segmentation 改變時"""
        if node:
            self._extractButton.enabled = True
            self._statusLabel.text = f"已選擇 Segment：{self._segmentSelector.currentSegmentID() or '未指定'}"

    def onExtractMandible(self):
        with slicer.util.tryWithErrorDisplay(_("Failed to build HU layers."), waitCursor=True):
            # 從 Target Segment Selector 取得資訊
            dentalSegNode = self._segmentSelector.currentNode()
            selectedSegmentId = self._segmentSelector.currentSegmentID()

            if not dentalSegNode or not selectedSegmentId:
                slicer.util.errorDisplay("請選擇 Target Segment！")
                return

            volumeNode = self._volumeSelector.currentNode()
            if not volumeNode:
                volumeNode = self._segmentationWidget.getCurrentVolumeNode()
            if not volumeNode:
                slicer.util.errorDisplay("請選擇 CT Volume！")
                return

            newSegNode = self.logic.extractMandible(dentalSegNode, volumeNode, selectedSegmentId)
            if newSegNode:
                layerCount = newSegNode.GetSegmentation().GetNumberOfSegments() - 2
                self._statusLabel.text = f"✅ 完成！\n已成功建立棕色＋白色 + {layerCount} 個 HU 分層。"


#
# Hu_ThresholdLogic
#


class Hu_ThresholdLogic(ScriptedLoadableModuleLogic):

    HU_LAYERS = [
        ("0-100",    0,    100,  0.00, 0.00, 0.00),   # 黑色
        ("100-250",  101,  250,  0.50, 0.00, 0.50),  # 紫色
        ("250-400",  251,  400,  0.00, 0.00, 1.00),  # 藍色
        ("400-600",  401,  600,  0.00, 0.80, 0.00),  # 綠色
        ("600-800",  601,  800,  1.00, 0.00, 0.00),  # 紅色
        ("800-1000", 801, 1000,  1.00, 1.00, 0.00),  # 黃色
    ]

    def extractMandible(self, dentalSegNode, volumeNode, selectedSegmentId):
        segmentation = dentalSegNode.GetSegmentation()
        if not selectedSegmentId or not segmentation.GetSegment(selectedSegmentId):
            slicer.util.errorDisplay("無效的 Target Segment！")
            return None

        segName = segmentation.GetSegment(selectedSegmentId).GetName()
        logging.info(f"開始處理 segment：{segName}")

        # 建立新 Segmentation Node
        newSegNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        newSegNode.SetName(f"Hu_Threshold_{segName}")
        newSegNode.CreateDefaultDisplayNodes()
        newSegNode.SetReferenceImageGeometryParameterFromVolumeNode(volumeNode)

        # Subject Hierarchy 整理
        shNode = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
        volumeItem = shNode.GetItemByDataNode(volumeNode)
        if volumeItem:
            parentItem = shNode.GetItemParent(volumeItem)
            shNode.SetItemParent(shNode.GetItemByDataNode(newSegNode), parentItem)

        # 複製棕色與白色 Segment
        seg = newSegNode.GetSegmentation()
        seg.CopySegmentFromSegmentation(dentalSegNode.GetSegmentation(), selectedSegmentId)
        mandibleCopiedId = seg.GetNthSegmentID(0)
        seg.GetSegment(mandibleCopiedId).SetName(segName)
        seg.GetSegment(mandibleCopiedId).SetColor(170/255, 85/255, 0.0)

        seg.CopySegmentFromSegmentation(dentalSegNode.GetSegmentation(), selectedSegmentId)
        whiteSeg = seg.GetSegment(seg.GetNthSegmentID(1))
        whiteSeg.SetName(segName + "_white")
        whiteSeg.SetColor(1.0, 1.0, 1.0)

        # 建立 Binary Labelmap
        if not seg.ContainsRepresentation(slicer.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName()):
            seg.CreateRepresentation(slicer.vtkSegmentationConverter.GetSegmentationBinaryLabelmapRepresentationName())

        # 取得陣列並建立 HU 分層
        import numpy as np
        segArray = slicer.util.arrayFromSegmentBinaryLabelmap(newSegNode, mandibleCopiedId, volumeNode)
        ctArray = slicer.util.arrayFromVolume(volumeNode)

        for name, huLow, huHigh, r, g, b in self.HU_LAYERS:
            layerMask = (segArray > 0) & (ctArray >= huLow) & (ctArray <= huHigh)
            if not np.any(layerMask):
                continue

            newSegId = seg.AddEmptySegment(name)
            newSeg = seg.GetSegment(newSegId)
            newSeg.SetName(name)
            newSeg.SetColor(r, g, b)

            slicer.util.updateSegmentBinaryLabelmapFromArray(
                layerMask.astype(np.uint8), newSegNode, newSegId, volumeNode
            )

        newSegNode.GetDisplayNode().SetVisibility(True)
        return newSegNode


# Test class (可保留)
class Hu_ThresholdTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()
    def runTest(self):
        self.setUp()
        self.delayDisplay("Test passed")